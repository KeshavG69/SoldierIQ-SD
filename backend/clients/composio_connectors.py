"""
Composio connectors — let a user connect third-party apps (Gmail, Slack, Jira…),
choose which of each app's actions the chat agent may use, and hand the agent
exactly those actions as tools.

Ported from enterprise-fastapi (routers/composio.py + utils/composio_utils.py)
and enterprise-search-frontend (Tool / ToolAction / ChatTool / ChatAction
Mongo models, /api/ui/actions). Here everything lives in Postgres:

  connector_tools          app catalog (seeded from config/composio_connectors.json)
  connector_tool_actions   action catalog: code, title, description, read|write
  user_connector_tools     a user's on/off switch per app
  user_connector_actions   a user's on/off switch per action (max ACTION_LIMIT on)
  composio_connections     a user's Composio connection per app (INITIATED/ACTIVE)

The agent gets an action only when: the app is connected (ACTIVE), the user
has the app switched on, and the action switched on. No row = off.

- The Composio "user" (entity) is `{org_id}_{user_id}`, so a person's
  connections in one org are never visible to the agent in another org, and
  they never collide with the sidebar's Google Drive/SharePoint ingestion
  connections (which use the bare user_id).
- auth configs: an app may pin `auth_config_id`; otherwise we reuse (or create
  once) a Composio-managed auth config for the toolkit, so no OAuth app
  registration is needed on our side.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.logger import logger
from app.settings import settings
from clients.postgres_client import get_postgres_client

# Same cap as enterprise's actions tab: every enabled action is a tool schema
# in the agent's context, so keep the total small.
ACTION_LIMIT = 15

_SEED_PATH = Path(__file__).resolve().parent.parent / "config" / "composio_connectors.json"

_client = None
_client_lock = threading.Lock()
_auth_config_cache: Dict[str, str] = {}
_auth_config_lock = threading.Lock()

# Tool schemas are fetched from Composio on every agent build otherwise; cache
# the wrapped toolkits per (entity, actions) for a few minutes.
_TOOLS_TTL_S = 600
_tools_cache: Dict[tuple, tuple] = {}


class ComposioConnectorError(RuntimeError):
    """A user-facing connector error (bad service, limit reached, …)."""


def _composio():
    """Composio client whose tools come back as Agno toolkits."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if not settings.COMPOSIO_API_KEY:
                    raise ComposioConnectorError("COMPOSIO_API_KEY is not configured")
                from composio import Composio
                from clients.composio_agno_provider import AgnoProvider

                _client = Composio(api_key=settings.COMPOSIO_API_KEY, provider=AgnoProvider())
                logger.info("✅ Composio client initialized (agent connectors)")
    return _client


def composio_entity(organization_id: Optional[str], user_id: str) -> str:
    return f"{organization_id}_{user_id}" if organization_id else str(user_id)


def _org(organization_id: Optional[str]) -> str:
    # NULLs never collide under a UNIQUE/PK constraint, so "no org" is stored as ''.
    return organization_id or ""


async def _pool():
    return await get_postgres_client().get_pool()


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

# The catalog only changes when seed_catalog runs (startup), so keep it in
# memory instead of re-reading ~350 action rows on every Connectors open.
_CATALOG_TTL_S = 300
_catalog: Optional[Dict[str, Any]] = None
_catalog_loaded_at = 0.0
_catalog_lock = asyncio.Lock()


def invalidate_catalog() -> None:
    global _catalog
    _catalog = None


async def get_catalog() -> Dict[str, Any]:
    """{"tools": [...], "actions_by_tool": {tool_id: [...]}, "tool_by_name": {...}}
    with ids as strings, active rows only, in display order."""
    global _catalog, _catalog_loaded_at
    if _catalog is not None and time.monotonic() - _catalog_loaded_at < _CATALOG_TTL_S:
        return _catalog
    async with _catalog_lock:
        if _catalog is not None and time.monotonic() - _catalog_loaded_at < _CATALOG_TTL_S:
            return _catalog
        async with (await _pool()).acquire() as conn:
            tools = await conn.fetch(
                "SELECT * FROM connector_tools WHERE status = 'ACTIVE' ORDER BY sort_order, title"
            )
            actions = await conn.fetch(
                """SELECT id, tool_id, code, title, description, type, scope_requirements
                   FROM connector_tool_actions
                   WHERE status = 'ACTIVE' ORDER BY sort_order, title"""
            )
        tool_list = [{**dict(t), "id": str(t["id"])} for t in tools]
        tool_by_id = {t["id"]: t for t in tool_list}
        actions_by_tool: Dict[str, List[Dict[str, Any]]] = {}
        action_by_code: Dict[str, Dict[str, Any]] = {}
        action_by_id: Dict[str, Dict[str, Any]] = {}
        for a in actions:
            req = a["scope_requirements"]
            action = {
                "id": str(a["id"]), "code": a["code"], "title": a["title"],
                "description": a["description"], "type": a["type"],
                "scope_requirements": json.loads(req) if isinstance(req, str) else req,
                "service": tool_by_id.get(str(a["tool_id"]), {}).get("name"),
            }
            actions_by_tool.setdefault(str(a["tool_id"]), []).append(action)
            action_by_code[action["code"]] = action
            action_by_id[action["id"]] = action
        _catalog = {
            "tools": tool_list,
            "actions_by_tool": actions_by_tool,
            "tool_by_name": {t["name"]: t for t in tool_list},
            "action_by_code": action_by_code,
            "action_by_id": action_by_id,
        }
        _catalog_loaded_at = time.monotonic()
        return _catalog


async def get_tool(service: str) -> Dict[str, Any]:
    tool = (await get_catalog())["tool_by_name"].get((service or "").lower().strip())
    if not tool:
        raise ComposioConnectorError(f"Unsupported connector: {service}")
    return tool


# ---------------------------------------------------------------------------
# Granted permissions (OAuth scopes)
#
# Providers like Google let users untick individual permissions at consent.
# Composio still marks the connection ACTIVE, so we read what was actually
# granted and treat actions whose required scopes weren't granted as
# unavailable: they're never given to the agent, can't be switched on, and the
# smart selector (setup_composio_service / select_additional_actions) can't
# pick them. Required scopes come from Composio's per-tool
# `scope_requirements` ({"all_of": [{"any_of": [...]}]}).
# ---------------------------------------------------------------------------

def _parse_scopes(raw: Any) -> Optional[List[str]]:
    if raw is None:
        return None
    if isinstance(raw, str):
        parts = raw.replace(",", " ").split()
    elif isinstance(raw, (list, tuple)):
        parts = [str(x).strip() for x in raw]
    else:
        return None
    parts = [p for p in parts if p]
    return parts or None


def _granted_from_account(acct: Any) -> Optional[List[str]]:
    d = acct.model_dump() if hasattr(acct, "model_dump") else dict(getattr(acct, "__dict__", {}))
    val = ((d.get("state") or {}).get("val") or {})
    return _parse_scopes(val.get("scope")) or _parse_scopes((d.get("data") or {}).get("scope"))


def action_available(action: Dict[str, Any], granted: Optional[List[str]]) -> bool:
    """True unless we know the grant misses a scope this action needs.
    Unknown grants (None) and actions without published requirements count
    as available — the error-mapping safety net covers those."""
    req = action.get("scope_requirements")
    if not req or granted is None:
        return True
    granted_set = set(granted)
    for group in req.get("all_of") or []:
        any_of = group.get("any_of") or []
        if any_of and not granted_set.intersection(any_of):
            return False
    return True


async def _granted_scopes(organization_id: Optional[str], user_id: str, service: str) -> Optional[List[str]]:
    """Scopes granted on the user's ACTIVE connection for `service` (None if
    not connected or unknown)."""
    async with (await _pool()).acquire() as conn:
        row = await conn.fetchrow(
            """SELECT granted_scopes FROM composio_connections
               WHERE organization_id = $1 AND user_id = $2 AND service = $3 AND status = 'ACTIVE'""",
            _org(organization_id), user_id, service,
        )
    return list(row["granted_scopes"]) if row and row["granted_scopes"] is not None else None


async def available_actions(organization_id: Optional[str], user_id: str, service: str) -> List[Dict[str, Any]]:
    """The app's catalog actions this user's grant allows."""
    catalog = await get_catalog()
    tool = catalog["tool_by_name"].get(service)
    if not tool:
        return []
    granted = await _granted_scopes(organization_id, user_id, service)
    return [a for a in catalog["actions_by_tool"].get(tool["id"], []) if action_available(a, granted)]


def _resolve_auth_config_id(tool: Dict[str, Any]) -> str:
    if tool.get("auth_config_id"):
        return tool["auth_config_id"]
    toolkit = tool["toolkit"]
    if toolkit in _auth_config_cache:
        return _auth_config_cache[toolkit]
    with _auth_config_lock:
        if toolkit in _auth_config_cache:
            return _auth_config_cache[toolkit]
        c = _composio()
        res = c.auth_configs.list(toolkit_slug=toolkit, is_composio_managed=True)
        existing = next(
            (a for a in getattr(res, "items", []) or []
             if str(getattr(a, "status", "")).upper() == "ENABLED"),
            None,
        )
        if existing is not None:
            auth_config_id = existing.id
        else:
            created = c.auth_configs.create(
                toolkit, {"type": "use_composio_managed_auth", "name": f"SoldierIQ {tool['title']}"}
            )
            auth_config_id = created.id
            logger.info(f"🆕 Created Composio-managed auth config for {toolkit}: {auth_config_id}")
        _auth_config_cache[toolkit] = auth_config_id
        return auth_config_id


# ---------------------------------------------------------------------------
# Connections (composio_connections)
# ---------------------------------------------------------------------------

async def _get_connection(organization_id: Optional[str], user_id: str, service: str) -> Optional[Dict[str, Any]]:
    async with (await _pool()).acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM composio_connections WHERE organization_id = $1 AND user_id = $2 AND service = $3",
            _org(organization_id), user_id, service,
        )
    return dict(row) if row else None


async def initiate_connection(
    organization_id: Optional[str],
    user_id: str,
    service: str,
    callback_url: Optional[str],
) -> Dict[str, Any]:
    """Start Composio's hosted OAuth flow and record a pending connection."""
    tool = await get_tool(service)
    service = tool["name"]

    existing = await _get_connection(organization_id, user_id, service)
    if existing and existing.get("status") == "ACTIVE":
        granted = existing.get("granted_scopes")
        granted = list(granted) if granted is not None else None
        actions = (await get_catalog())["actions_by_tool"].get(tool["id"], [])
        if all(action_available(a, granted) for a in actions):
            raise ComposioConnectorError(f"{tool['title']} is already connected")
        # Connected with limited access: allow reconnecting to grant more.
        # The user's switches are keyed by app, so they survive.
    if existing and existing.get("connected_account_id"):
        # A leftover pending attempt (or the limited connection being
        # replaced) — drop it so Composio doesn't accumulate stale accounts.
        await asyncio.to_thread(_delete_account_quietly, existing["connected_account_id"])

    auth_config_id = await asyncio.to_thread(_resolve_auth_config_id, tool)
    req = await asyncio.to_thread(
        _composio().connected_accounts.link,
        user_id=composio_entity(organization_id, user_id),
        auth_config_id=auth_config_id,
        callback_url=callback_url,
    )
    connected_account_id = getattr(req, "id", None)
    auth_url = getattr(req, "redirect_url", None)
    if not connected_account_id or not auth_url:
        raise ComposioConnectorError("Composio did not return an auth URL")

    async with (await _pool()).acquire() as conn:
        await conn.execute(
            """
            INSERT INTO composio_connections (organization_id, user_id, service, toolkit, connected_account_id, status)
            VALUES ($1, $2, $3, $4, $5, 'INITIATED')
            ON CONFLICT (organization_id, user_id, service) DO UPDATE SET
                toolkit = EXCLUDED.toolkit,
                connected_account_id = EXCLUDED.connected_account_id,
                status = 'INITIATED',
                granted_scopes = NULL,
                updated_at = NOW()
            """,
            _org(organization_id), user_id, service, tool["toolkit"], connected_account_id,
        )
    logger.info(f"🔗 Composio connect started: service={service} user={user_id[:8]}…")
    return {"service": service, "auth_url": auth_url, "connected_account_id": connected_account_id}


def _delete_account_quietly(connected_account_id: str) -> None:
    try:
        _composio().connected_accounts.delete(connected_account_id)
    except Exception as e:  # already gone on Composio's side is fine
        logger.warning(f"Composio delete {connected_account_id} failed: {e}")


async def disconnect(organization_id: Optional[str], user_id: str, service: str) -> bool:
    """Delete the Composio account (revokes tokens) and our record, and switch
    the app + its actions off for this user (as enterprise does)."""
    service = (service or "").lower().strip()
    record = await _get_connection(organization_id, user_id, service)
    if not record:
        return False
    if record.get("connected_account_id"):
        await asyncio.to_thread(_delete_account_quietly, record["connected_account_id"])
    async with (await _pool()).acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM composio_connections WHERE id = $1", record["id"])
            tool_id = await conn.fetchval("SELECT id FROM connector_tools WHERE name = $1", service)
            if tool_id:
                await _set_tool_enabled(conn, organization_id, user_id, tool_id, False)
    logger.info(f"🔌 Composio disconnected: service={service} user={user_id[:8]}…")
    return True


def _fetch_account(connected_account_id: str) -> tuple[Optional[str], Optional[List[str]]]:
    """(status, granted scopes) for a Composio connected account."""
    try:
        acct = _composio().connected_accounts.get(connected_account_id)
        status = str(getattr(acct, "status", "") or "").upper() or None
        return status, _granted_from_account(acct)
    except Exception as e:
        logger.warning(f"Composio account lookup {connected_account_id} failed: {e}")
        return None, None


# Composio link sessions expire long before this; older pending rows are dead.
_PENDING_WINDOW = timedelta(minutes=30)
_PENDING_STATUSES = {"INITIATED", "INITIALIZING"}


def _is_pending(record: Dict[str, Any]) -> bool:
    if record.get("status") not in _PENDING_STATUSES or not record.get("connected_account_id"):
        return False
    updated = record.get("updated_at")
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)
    return updated is None or datetime.now(timezone.utc) - updated < _PENDING_WINDOW


async def _refresh_pending(record: Dict[str, Any]) -> Dict[str, Any]:
    """In-progress logins flip to ACTIVE once the user finishes OAuth. We don't
    get a server-side webhook, so we ask Composio when the row is read — only
    for rows still mid-login (each check is a ~1s Composio round trip)."""
    if not _is_pending(record):
        return record
    live, granted = await asyncio.to_thread(_fetch_account, record["connected_account_id"])
    if live and live != record.get("status"):
        async with (await _pool()).acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """UPDATE composio_connections SET status = $2, granted_scopes = $3, updated_at = NOW()
                       WHERE id = $1""",
                    uuid.UUID(str(record["id"])), live, granted,
                )
                if live == "ACTIVE":
                    await _apply_grant(conn, record, granted)
        record = {**record, "status": live, "granted_scopes": granted}
        if live == "ACTIVE" and granted is not None:
            logger.info(f"🔐 {record['service']} granted scopes: {granted}")
    return record


async def _apply_grant(conn, record: Dict[str, Any], granted: Optional[List[str]]) -> None:
    """A connection just became ACTIVE: switch off actions its grant can't run
    (e.g. enabled earlier by setup_composio_service), then apply defaults."""
    tool = (await get_catalog())["tool_by_name"].get(record["service"])
    if tool:
        blocked = [
            uuid.UUID(a["id"]) for a in (await get_catalog())["actions_by_tool"].get(tool["id"], [])
            if not action_available(a, granted)
        ]
        if blocked:
            await conn.execute(
                """UPDATE user_connector_actions SET enabled = FALSE, updated_at = NOW()
                   WHERE organization_id = $1 AND user_id = $2 AND action_id = ANY($3::uuid[]) AND enabled""",
                record["organization_id"], record["user_id"], blocked,
            )
            logger.info(f"🚫 {record['service']}: {len(blocked)} action(s) unavailable with the granted scopes")
    await _enable_defaults(conn, record, granted)


async def _enable_defaults(conn, record: Dict[str, Any], granted: Optional[List[str]] = None) -> None:
    """On a fresh connection, switch the app on plus its read-only actions (up
    to the remaining limit), so it works without a trip to the settings. Users
    who already have toggles for this app keep them."""
    org, user_id, service = record["organization_id"], record["user_id"], record["service"]
    tool_id = await conn.fetchval("SELECT id FROM connector_tools WHERE name = $1", service)
    if not tool_id:
        return
    # Keep the user's choices if any action of this app is switched on
    # (after _apply_grant pruned the ones the grant can't run).
    has_settings = await conn.fetchval(
        """SELECT EXISTS (SELECT 1 FROM user_connector_actions ua
                          JOIN connector_tool_actions a ON a.id = ua.action_id
                          WHERE ua.organization_id = $1 AND ua.user_id = $2 AND a.tool_id = $3
                            AND ua.enabled)""",
        org, user_id, tool_id,
    )
    await _upsert_tool_toggle(conn, org, user_id, tool_id, True)
    if has_settings:
        return
    remaining = ACTION_LIMIT - await _count_enabled(conn, org, user_id)
    if remaining <= 0:
        return
    catalog_actions = (await get_catalog())["actions_by_tool"].get(str(tool_id), [])
    picks = [
        uuid.UUID(a["id"]) for a in catalog_actions
        if a["type"] == "read" and action_available(a, granted)
    ][:remaining]
    if not picks:
        return
    await conn.execute(
        """
        INSERT INTO user_connector_actions (organization_id, user_id, action_id, enabled)
        SELECT $1, $2, unnest($3::uuid[]), TRUE
        ON CONFLICT (organization_id, user_id, action_id) DO UPDATE SET enabled = TRUE, updated_at = NOW()
        """,
        org, user_id, picks,
    )


async def confirm_connection(
    organization_id: Optional[str], user_id: str, connected_account_id: str
) -> Optional[Dict[str, Any]]:
    """Called from the OAuth callback page: re-check the account with Composio
    and mark our row ACTIVE. Scoped to the caller so nobody can flip someone
    else's row."""
    async with (await _pool()).acquire() as conn:
        row = await conn.fetchrow(
            """SELECT * FROM composio_connections
               WHERE organization_id = $1 AND user_id = $2 AND connected_account_id = $3""",
            _org(organization_id), user_id, connected_account_id,
        )
    if not row:
        return None
    record = await _refresh_pending(dict(row))
    return {"service": record["service"], "status": record.get("status"),
            "connected": record.get("status") == "ACTIVE"}


# ---------------------------------------------------------------------------
# Toggles (user_connector_tools / user_connector_actions)
# ---------------------------------------------------------------------------

async def _count_enabled(conn, org: str, user_id: str) -> int:
    return await conn.fetchval(
        """SELECT COUNT(*) FROM user_connector_actions ua
           JOIN connector_tool_actions a ON a.id = ua.action_id AND a.status = 'ACTIVE'
           WHERE ua.organization_id = $1 AND ua.user_id = $2 AND ua.enabled""",
        org, user_id,
    )


async def _upsert_tool_toggle(conn, org: str, user_id: str, tool_id: Any, enabled: bool) -> None:
    tool_id = tool_id if isinstance(tool_id, uuid.UUID) else uuid.UUID(str(tool_id))
    await conn.execute(
        """INSERT INTO user_connector_tools (organization_id, user_id, tool_id, enabled)
           VALUES ($1, $2, $3, $4)
           ON CONFLICT (organization_id, user_id, tool_id) DO UPDATE SET enabled = $4, updated_at = NOW()""",
        org, user_id, tool_id, enabled,
    )


async def _set_tool_enabled(conn, organization_id: Optional[str], user_id: str, tool_id: Any, enabled: bool) -> None:
    org = _org(organization_id)
    await _upsert_tool_toggle(conn, org, user_id, tool_id, enabled)
    if not enabled:
        # Turning an app off turns all its actions off too (enterprise behaviour).
        await conn.execute(
            """UPDATE user_connector_actions ua SET enabled = FALSE, updated_at = NOW()
               FROM connector_tool_actions a
               WHERE a.id = ua.action_id AND a.tool_id = $3
                 AND ua.organization_id = $1 AND ua.user_id = $2""",
            org, user_id, tool_id,
        )


async def set_tool_enabled(organization_id: Optional[str], user_id: str, tool_id: str, enabled: bool) -> None:
    """One statement (one round trip): upsert the app switch and, when turning
    it off, switch all its actions off too (enterprise behaviour)."""
    async with (await _pool()).acquire() as conn:
        found = await conn.fetchval(
            """
            WITH t AS (SELECT id FROM connector_tools WHERE id = $3),
            up AS (
                INSERT INTO user_connector_tools (organization_id, user_id, tool_id, enabled)
                SELECT $1, $2, id, $4 FROM t
                ON CONFLICT (organization_id, user_id, tool_id)
                DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = NOW()
                RETURNING 1
            ),
            off AS (
                UPDATE user_connector_actions ua SET enabled = FALSE, updated_at = NOW()
                FROM connector_tool_actions a
                WHERE NOT $4 AND a.id = ua.action_id AND a.tool_id = $3
                  AND ua.organization_id = $1 AND ua.user_id = $2 AND ua.enabled
                RETURNING 1
            )
            SELECT COUNT(*) FROM t
            """,
            _org(organization_id), user_id, uuid.UUID(tool_id), enabled,
        )
    if not found:
        raise ComposioConnectorError("Unknown connector")


async def set_action_enabled(organization_id: Optional[str], user_id: str, action_id: str, enabled: bool) -> None:
    """One statement (one round trip): check the action exists and, when
    enabling, that the user is under ACTION_LIMIT; then upsert the action
    switch and switch its app on (enabling an action implies the app is on).
    Enabling an action the user's granted permissions can't run is refused."""
    if enabled:
        action = (await get_catalog())["action_by_id"].get(action_id)
        if action and action.get("scope_requirements"):
            granted = await _granted_scopes(organization_id, user_id, action["service"])
            if not action_available(action, granted):
                app = (await get_catalog())["tool_by_name"].get(action["service"], {}).get("title", "this app")
                raise ComposioConnectorError(
                    f"\"{action['title']}\" needs a permission you didn't grant when connecting {app}. "
                    f"Reconnect {app} and allow access to enable it."
                )
    async with (await _pool()).acquire() as conn:
        row = await conn.fetchrow(
            """
            WITH act AS (
                SELECT id, tool_id FROM connector_tool_actions WHERE id = $3 AND status = 'ACTIVE'
            ),
            cnt AS (
                SELECT COUNT(*) AS n FROM user_connector_actions ua
                JOIN connector_tool_actions a ON a.id = ua.action_id AND a.status = 'ACTIVE'
                WHERE ua.organization_id = $1 AND ua.user_id = $2 AND ua.enabled AND ua.action_id <> $3
            ),
            ok AS (SELECT act.* FROM act, cnt WHERE NOT $4 OR cnt.n < $5),
            up_action AS (
                INSERT INTO user_connector_actions (organization_id, user_id, action_id, enabled)
                SELECT $1, $2, id, $4 FROM ok
                ON CONFLICT (organization_id, user_id, action_id)
                DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = NOW()
                RETURNING 1
            ),
            up_tool AS (
                INSERT INTO user_connector_tools (organization_id, user_id, tool_id, enabled)
                SELECT $1, $2, tool_id, TRUE FROM ok WHERE $4
                ON CONFLICT (organization_id, user_id, tool_id)
                DO UPDATE SET enabled = TRUE, updated_at = NOW()
                RETURNING 1
            )
            SELECT (SELECT COUNT(*) FROM act) AS found, (SELECT COUNT(*) FROM up_action) AS written
            """,
            _org(organization_id), user_id, uuid.UUID(action_id), enabled, ACTION_LIMIT,
        )
    if not row["found"]:
        raise ComposioConnectorError("Unknown action")
    if not row["written"]:
        raise ComposioConnectorError(
            f"You can enable at most {ACTION_LIMIT} actions. Disable one to enable another."
        )


# ---------------------------------------------------------------------------
# Listing (what the Connectors UI renders)
# ---------------------------------------------------------------------------

# Everything user-specific the Connectors screen needs, in one round trip.
_USER_STATE_SQL = """
SELECT
  COALESCE((SELECT json_agg(json_build_object(
              'id', id, 'organization_id', organization_id, 'user_id', user_id,
              'service', service, 'status', status,
              'connected_account_id', connected_account_id, 'updated_at', updated_at,
              'granted_scopes', granted_scopes))
            FROM composio_connections WHERE organization_id = $1 AND user_id = $2), '[]') AS connections,
  COALESCE((SELECT json_agg(tool_id) FROM user_connector_tools
            WHERE organization_id = $1 AND user_id = $2 AND enabled), '[]') AS tools_on,
  COALESCE((SELECT json_agg(action_id) FROM user_connector_actions
            WHERE organization_id = $1 AND user_id = $2 AND enabled), '[]') AS actions_on
"""


async def _user_state(org: str, user_id: str) -> Dict[str, Any]:
    async with (await _pool()).acquire() as conn:
        row = await conn.fetchrow(_USER_STATE_SQL, org, user_id)
    return {k: json.loads(row[k]) for k in ("connections", "tools_on", "actions_on")}


async def list_connectors(organization_id: Optional[str], user_id: str) -> Dict[str, Any]:
    """Every active app with its actions and this user's connection + toggles
    (equivalent of enterprise's GET /api/ui/actions). Normally one DB round
    trip: the catalog comes from memory."""
    org = _org(organization_id)
    catalog, state = await asyncio.gather(get_catalog(), _user_state(org, user_id))

    # A login that just finished turns ACTIVE here and gets its default
    # toggles, so re-read the (cheap) user state if that happened.
    pending = [c for c in state["connections"] if _is_pending(c)]
    if pending:
        refreshed = await asyncio.gather(*(_refresh_pending(c) for c in pending))
        if any(r.get("status") == "ACTIVE" for r in refreshed):
            state = await _user_state(org, user_id)
        else:
            by_id = {r["id"]: r for r in refreshed}
            state["connections"] = [by_id.get(c["id"], c) for c in state["connections"]]

    conn_by_service = {c["service"]: c for c in state["connections"]}
    tools_on = set(state["tools_on"])
    actions_on = set(state["actions_on"])
    valid_action_ids = set()

    out = []
    for t in catalog["tools"]:
        c = conn_by_service.get(t["name"])
        connected = bool(c and c.get("status") == "ACTIVE")
        granted = c.get("granted_scopes") if connected else None
        actions = []
        for a in catalog["actions_by_tool"].get(t["id"], []):
            available = action_available(a, granted)
            actions.append({
                "id": a["id"], "code": a["code"], "title": a["title"],
                "description": a["description"], "type": a["type"],
                "available": available,
                "enabled": available and a["id"] in actions_on,
            })
            if available:
                valid_action_ids.add(a["id"])
        out.append({
            "id": t["id"],
            "service": t["name"],
            "name": t["title"],
            "category": t["category"],
            "description": t["description"],
            "logo": t["logo"],
            "enabled": t["id"] in tools_on,
            "status": c.get("status") if c else None,
            "connected": connected,
            # Connected, but the user didn't grant everything some actions need.
            "limited_access": connected and any(not a["available"] for a in actions),
            "actions": actions,
        })
    total_enabled = len(actions_on & valid_action_ids)
    return {"connectors": out, "total_enabled": total_enabled, "limit": ACTION_LIMIT}


# ---------------------------------------------------------------------------
# Agent tools
# ---------------------------------------------------------------------------

async def get_enabled_actions(organization_id: Optional[str], user_id: str) -> Dict[str, List[str]]:
    """{app title: [action codes]} the agent may use: connected + app on + action on."""
    async with (await _pool()).acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT t.title, a.code, c.granted_scopes
            FROM composio_connections c
            JOIN connector_tools t ON t.name = c.service AND t.status = 'ACTIVE'
            JOIN user_connector_tools ut
              ON ut.tool_id = t.id AND ut.organization_id = c.organization_id
             AND ut.user_id = c.user_id AND ut.enabled
            JOIN connector_tool_actions a ON a.tool_id = t.id AND a.status = 'ACTIVE'
            JOIN user_connector_actions ua
              ON ua.action_id = a.id AND ua.organization_id = c.organization_id
             AND ua.user_id = c.user_id AND ua.enabled
            WHERE c.organization_id = $1 AND c.user_id = $2 AND c.status = 'ACTIVE'
            ORDER BY t.sort_order, a.sort_order
            """,
            _org(organization_id), user_id,
        )
    action_by_code = (await get_catalog())["action_by_code"]
    out: Dict[str, List[str]] = {}
    for r in rows:
        granted = list(r["granted_scopes"]) if r["granted_scopes"] is not None else None
        action = action_by_code.get(r["code"])
        if action and not action_available(action, granted):
            continue  # permission not granted — never offered to the agent
        out.setdefault(r["title"], []).append(r["code"])
    return out


def _load_tools(entity: str, actions: tuple) -> List[Any]:
    key = (entity, actions)
    hit = _tools_cache.get(key)
    if hit and time.monotonic() - hit[0] < _TOOLS_TTL_S:
        return hit[1]
    tools = _composio().tools.get(user_id=entity, tools=list(actions))
    _tools_cache[key] = (time.monotonic(), tools)
    return tools


async def get_agent_tools(
    organization_id: Optional[str], user_id: Optional[str]
) -> tuple[List[Any], List[str]]:
    """Agno toolkits for the actions this user enabled on connected apps, plus
    the display names of those apps (for the agent's instructions). Never
    raises — a Composio outage must not break normal knowledge-base chat."""
    if not user_id or not settings.COMPOSIO_API_KEY:
        return [], []
    try:
        enabled = await get_enabled_actions(organization_id, user_id)
        if not enabled:
            return [], []
        actions = tuple(sorted({code for codes in enabled.values() for code in codes}))
        tools = await asyncio.to_thread(
            _load_tools, composio_entity(organization_id, user_id), actions
        )
        names = list(enabled.keys())
        logger.info(f"🧰 Loaded {len(tools)} Composio tools for {', '.join(names)}")
        return list(tools), names
    except Exception as e:
        logger.error(f"❌ Failed to load Composio tools: {e}")
        return [], []


# ---------------------------------------------------------------------------
# Startup: tables + catalog seed
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS public.composio_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    service TEXT NOT NULL,
    toolkit TEXT NOT NULL,
    connected_account_id TEXT,
    status TEXT NOT NULL DEFAULT 'INITIATED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id, service)
);
CREATE INDEX IF NOT EXISTS idx_composio_conn_account
    ON public.composio_connections USING btree (connected_account_id);

CREATE TABLE IF NOT EXISTS public.connector_tools (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT,
    logo TEXT,
    toolkit TEXT NOT NULL,
    auth_config_id TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.connector_tool_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_id UUID NOT NULL REFERENCES public.connector_tools(id) ON DELETE CASCADE,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    type TEXT NOT NULL DEFAULT 'read',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    sort_order INT NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_connector_actions_tool ON public.connector_tool_actions (tool_id);

CREATE TABLE IF NOT EXISTS public.user_connector_tools (
    organization_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    tool_id UUID NOT NULL REFERENCES public.connector_tools(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, user_id, tool_id)
);

CREATE TABLE IF NOT EXISTS public.user_connector_actions (
    organization_id TEXT NOT NULL DEFAULT '',
    user_id TEXT NOT NULL,
    action_id UUID NOT NULL REFERENCES public.connector_tool_actions(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (organization_id, user_id, action_id)
);
-- Enabled-action lookups (limit count, agent tools, Connectors screen).
CREATE INDEX IF NOT EXISTS idx_user_connector_actions_enabled
    ON public.user_connector_actions (organization_id, user_id) WHERE enabled;

-- Granular permissions: what each action needs, and what each connection got.
ALTER TABLE public.connector_tool_actions ADD COLUMN IF NOT EXISTS scope_requirements JSONB;
ALTER TABLE public.composio_connections ADD COLUMN IF NOT EXISTS granted_scopes TEXT[];
"""


async def seed_catalog() -> None:
    """Upsert apps + actions from config/composio_connectors.json. Updates
    labels/metadata but never re-activates, so an app or action deactivated in
    the DB stays deactivated across restarts. Apps/actions no longer in the
    file are retired (INACTIVE). Nothing is deleted."""
    with open(_SEED_PATH) as f:
        seed = json.load(f)
    async with (await _pool()).acquire() as conn:
        async with conn.transaction():
            for t_order, (name, cfg) in enumerate(seed.items()):
                tool_id = await conn.fetchval(
                    """
                    INSERT INTO connector_tools (name, title, description, category, logo, toolkit, auth_config_id, sort_order)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (name) DO UPDATE SET
                        title = EXCLUDED.title, description = EXCLUDED.description,
                        category = EXCLUDED.category, logo = EXCLUDED.logo,
                        toolkit = EXCLUDED.toolkit, auth_config_id = EXCLUDED.auth_config_id,
                        sort_order = EXCLUDED.sort_order, updated_at = NOW()
                    RETURNING id
                    """,
                    name, cfg["name"], cfg.get("description"), cfg.get("category"), cfg.get("logo"),
                    cfg["toolkit"], cfg.get("auth_config_id"), t_order,
                )
                await conn.executemany(
                    """
                    INSERT INTO connector_tool_actions
                        (tool_id, code, title, description, type, sort_order, scope_requirements)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    ON CONFLICT (code) DO UPDATE SET
                        tool_id = EXCLUDED.tool_id, title = EXCLUDED.title,
                        description = EXCLUDED.description, type = EXCLUDED.type,
                        sort_order = EXCLUDED.sort_order,
                        scope_requirements = EXCLUDED.scope_requirements, updated_at = NOW()
                    """,
                    [
                        (tool_id, a["code"], a["title"], a.get("description"), a.get("type", "read"), a_order,
                         json.dumps(a["scope_requirements"]) if a.get("scope_requirements") else None)
                        for a_order, a in enumerate(cfg.get("actions", []))
                    ],
                )
            # Apps / actions removed from the seed file are retired (INACTIVE,
            # hidden everywhere) rather than deleted, so it's reversible.
            retired_apps = await conn.fetchval(
                """WITH r AS (UPDATE connector_tools SET status = 'INACTIVE', updated_at = NOW()
                              WHERE status = 'ACTIVE' AND NOT (name = ANY($1::text[])) RETURNING 1)
                   SELECT COUNT(*) FROM r""",
                list(seed.keys()),
            )
            seed_codes = [a["code"] for cfg in seed.values() for a in cfg.get("actions", [])]
            retired_actions = await conn.fetchval(
                """WITH r AS (UPDATE connector_tool_actions SET status = 'INACTIVE', updated_at = NOW()
                              WHERE status = 'ACTIVE' AND NOT (code = ANY($1::text[])) RETURNING 1)
                   SELECT COUNT(*) FROM r""",
                seed_codes,
            )
    invalidate_catalog()
    logger.info(
        f"✅ Connector catalog seeded: {len(seed)} apps"
        + (f" (retired {retired_apps} app(s), {retired_actions} action(s))" if retired_apps or retired_actions else "")
    )


async def _backfill_defaults() -> None:
    """ACTIVE connections that have no app toggle yet (made before per-action
    toggles existed) get the same defaults a fresh connection gets."""
    async with (await _pool()).acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.organization_id, c.user_id, c.service FROM composio_connections c
               JOIN connector_tools t ON t.name = c.service
               WHERE c.status = 'ACTIVE' AND NOT EXISTS (
                   SELECT 1 FROM user_connector_tools ut
                   WHERE ut.tool_id = t.id AND ut.organization_id = c.organization_id
                     AND ut.user_id = c.user_id)"""
        )
        for r in rows:
            async with conn.transaction():
                await _enable_defaults(conn, dict(r))
    if rows:
        logger.info(f"✅ Applied default action toggles to {len(rows)} existing connection(s)")


async def _backfill_granted_scopes() -> None:
    """ACTIVE connections made before we recorded granted permissions: fetch
    them from Composio once and switch off actions they can't run."""
    async with (await _pool()).acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, organization_id, user_id, service, connected_account_id
               FROM composio_connections
               WHERE status = 'ACTIVE' AND granted_scopes IS NULL AND connected_account_id IS NOT NULL"""
        )
    for r in rows:
        _, granted = await asyncio.to_thread(_fetch_account, r["connected_account_id"])
        if granted is None:
            continue  # provider didn't report scopes — leave as unknown
        async with (await _pool()).acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "UPDATE composio_connections SET granted_scopes = $2 WHERE id = $1", r["id"], granted
                )
                await _apply_grant(conn, dict(r), granted)
        logger.info(f"🔐 Recorded granted scopes for {r['service']} ({r['user_id'][:8]}…)")


async def ensure_tables() -> None:
    """Create tables if missing (mirrors schemas/postgres_schema.sql), seed the
    catalog, and give pre-existing connections default toggles."""
    async with (await _pool()).acquire() as conn:
        await conn.execute(_DDL)
    await seed_catalog()
    await _backfill_defaults()
    await _backfill_granted_scopes()
    await get_catalog()  # warm the in-memory catalog
