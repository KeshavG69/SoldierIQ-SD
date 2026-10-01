"""
Smart action selection for Composio connectors.

Ported from enterprise-fastapi/utils/smart_action_selector.py. Given what the
user asked for and an app, an LLM picks which of that app's actions to switch
on (and, when the per-user limit would be exceeded, which less relevant ones to
switch off). The result is written to user_connector_actions, so the chat agent
gets those actions from the next message on.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.logger import logger
from clients.composio_connectors import (
    ACTION_LIMIT, _org, _pool, _upsert_tool_toggle, available_actions, get_catalog,
)
from clients.ultimate_llm import get_llm

SELECTOR_MODEL = "google/gemini-3-flash-preview"


class _Selection(BaseModel):
    selected_actions: List[str] = Field(default_factory=list, description="Action codes to enable")
    actions_to_disconnect: List[str] = Field(default_factory=list, description="Currently enabled action codes to disable to stay under the limit")
    request_supported: bool = Field(
        default=True,
        description="False when none of the listed actions can do what the user asked",
    )
    reasoning: str = ""


def _norm(s: str) -> str:
    return re.sub(r"[\s_\-.]", "", (s or "").lower())


async def resolve_tool(service: str) -> Optional[Dict[str, Any]]:
    """Find an active app by key or title, ignoring case/separators
    ("google calendar", "google_calendar", "Google Calendar" → googlecalendar)."""
    target = _norm(service)
    for t in (await get_catalog())["tools"]:
        if target in (_norm(t["name"]), _norm(t["title"]), _norm(t["toolkit"])):
            return t
    return None


async def supported_services() -> List[str]:
    return [t["name"] for t in (await get_catalog())["tools"]]


async def _select_with_llm(
    query: str,
    task_description: str,
    service_title: str,
    current: List[Dict[str, Any]],
    available: List[Dict[str, Any]],
) -> _Selection:
    current_fmt = "\n".join(f"  - {a['code']}: {a['description']} (App: {a['app']})" for a in current) or "  (None selected yet)"
    available_fmt = "\n".join(f"  - {a['code']} [{a['type']}]: {a['description']}" for a in available)
    prompt = f"""You are an action selection expert for Composio integrations.

**User Query:** "{query}"
**Task Description:** {task_description}
**App:** {service_title}

**Currently Enabled Actions ({len(current)}/{ACTION_LIMIT}):**
{current_fmt}

**Available Actions from {service_title}:**
{available_fmt}

**Instructions:**
1. Review the CURRENTLY enabled actions first.
2. If they are SUFFICIENT for this specific query, return EMPTY lists — do not add unnecessary actions.
3. If actions are missing, select 2-10 additional actions that are essential. Do not repeat enabled ones.
4. **{ACTION_LIMIT} action limit:** {len(current)} are enabled now. If adding would exceed {ACTION_LIMIT}, list in
   "actions_to_disconnect" enabled actions that are clearly not needed for THIS task.
5. Include PREREQUISITE / discovery actions: if an action needs an ID, also select the search/list/get action
   that finds it (e.g. replying to an email needs a fetch/search action to find the thread).
6. Only use action codes exactly as listed above.
7. If NONE of the listed actions (enabled or available) can do what the user asked — for example they want to
   send or change something but only reading actions are listed — set "request_supported" to false and return
   empty lists. Do not substitute unrelated actions.

Examples:
- Query "Send an email to john", current ["GMAIL_SEND_EMAIL"] → selected [], disconnect [] (already sufficient).
- Query "Reply to the last email from Sarah", current [] → selected ["GMAIL_FETCH_EMAILS", "GMAIL_REPLY_TO_THREAD"].
"""
    llm = get_llm(model=SELECTOR_MODEL, provider="openrouter").with_structured_output(_Selection, method="function_calling")
    return await llm.ainvoke(prompt)


async def smart_select_actions(
    organization_id: Optional[str],
    user_id: str,
    query: str,
    service: str,
    task_description: str,
) -> Dict[str, Any]:
    """Pick and enable the actions this request needs for `service`.

    Returns the same shape as enterprise's smart_select_actions: success,
    actions_needed, added_actions, already_enabled_actions,
    disconnected_actions, total_actions, message, reasoning.
    """
    tool = await resolve_tool(service)
    if not tool:
        return {
            "success": False,
            "error": f"Service '{service}' is not supported",
            "message": f"'{service}' is not a supported app. Pick the closest match from supported_services and retry.",
            "supported_services": await supported_services(),
        }
    org = _org(organization_id)

    async with (await _pool()).acquire() as conn:
        current_rows = await conn.fetch(
            """SELECT a.code, a.description, t.name AS service, t.title AS app
               FROM user_connector_actions ua
               JOIN connector_tool_actions a ON a.id = ua.action_id AND a.status = 'ACTIVE'
               JOIN connector_tools t ON t.id = a.tool_id
               WHERE ua.organization_id = $1 AND ua.user_id = $2 AND ua.enabled
               ORDER BY t.sort_order, a.sort_order""",
            org, user_id,
        )

    current = [dict(r) for r in current_rows]
    # Only actions the user's granted permissions can run are candidates —
    # the model never sees the rest, so it can't pick them.
    available = await available_actions(organization_id, user_id, tool["name"])
    enabled_codes = {a["code"] for a in current}
    available_codes = [a["code"] for a in available]

    try:
        sel = await _select_with_llm(query, task_description, tool["title"], current, available)
        # Never trust codes the model made up.
        selected = [c for c in dict.fromkeys(sel.selected_actions) if c in available_codes and c not in enabled_codes]
        to_disconnect = [c for c in dict.fromkeys(sel.actions_to_disconnect) if c in enabled_codes and c not in selected]
        reasoning = sel.reasoning
        request_supported = sel.request_supported
    except Exception as e:
        logger.warning(f"Action-selection LLM failed ({e}); falling back to defaults for {tool['name']}")
        selected, to_disconnect = [], []
        reasoning = f"LLM selection failed ({e})."
        request_supported = True

    # The user's grant rules some of this app's actions out, and what's left
    # can't do the request → they need to reconnect with more access. The
    # model never saw the blocked actions; we only report that access is short.
    all_count = len((await get_catalog())["actions_by_tool"].get(tool["id"], []))
    if not request_supported and len(available) < all_count:
        return {
            "success": False,
            "actions_needed": True,
            "needs_more_access": True,
            "service": tool["name"],
            "added_actions": [],
            "already_enabled_actions": [],
            "total_actions": len(current),
            "reasoning": reasoning,
            "message": (
                f"{tool['title']} is connected without the permission this request needs. "
                f"The user must reconnect {tool['title']} and allow access."
            ),
        }

    service_enabled = [a["code"] for a in current if a["service"] == tool["name"]]
    if not selected:
        if service_enabled:
            return {
                "success": True,
                "actions_needed": False,
                "service": tool["name"],
                "added_actions": [],
                "already_enabled_actions": service_enabled,
                "total_actions": len(current),
                "reasoning": reasoning,
                "message": (
                    f"{len(service_enabled)} {tool['title']} action(s) are already enabled: "
                    f"{', '.join(service_enabled)}. No new actions needed."
                ),
            }
        # Nothing enabled for this app yet → enable a default set so the newly
        # set-up app is actually usable (read actions first, as on connect).
        room = max(0, ACTION_LIMIT - len(current))
        ordered = [a["code"] for a in available if a["type"] == "read"] + [a["code"] for a in available if a["type"] != "read"]
        selected = ordered[:min(room, 10)]
        reasoning = f"No {tool['title']} actions were enabled; auto-enabling {len(selected)} default action(s). {reasoning}".strip()
        if not selected:
            return {
                "success": False,
                "actions_needed": True,
                "service": tool["name"],
                "error": "Action limit reached",
                "message": f"The {ACTION_LIMIT}-action limit is reached. Ask the user to disable some actions in Connectors.",
                "total_actions": len(current),
            }

    if len(current) - len(to_disconnect) + len(selected) > ACTION_LIMIT:
        return {
            "success": False,
            "actions_needed": True,
            "service": tool["name"],
            "error": "Action limit would be exceeded",
            "message": (
                f"Cannot add {len(selected)} action(s): would exceed the {ACTION_LIMIT}-action limit "
                f"(currently {len(current)}). Ask the user to disable some actions in Connectors."
            ),
            "total_actions": len(current),
            "reasoning": reasoning,
        }

    async with (await _pool()).acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"connector-actions:{org}:{user_id}")
            if to_disconnect:
                await conn.execute(
                    """UPDATE user_connector_actions ua SET enabled = FALSE, updated_at = NOW()
                       FROM connector_tool_actions a
                       WHERE a.id = ua.action_id AND a.code = ANY($3::text[])
                         AND ua.organization_id = $1 AND ua.user_id = $2""",
                    org, user_id, to_disconnect,
                )
            await conn.execute(
                """INSERT INTO user_connector_actions (organization_id, user_id, action_id, enabled)
                   SELECT $1, $2, id, TRUE FROM connector_tool_actions WHERE code = ANY($3::text[])
                   ON CONFLICT (organization_id, user_id, action_id) DO UPDATE SET enabled = TRUE, updated_at = NOW()""",
                org, user_id, selected,
            )
            await _upsert_tool_toggle(conn, org, user_id, tool["id"], True)

    total = len(current) - len(to_disconnect) + len(selected)
    parts = []
    if to_disconnect:
        parts.append(f"Disabled {len(to_disconnect)} action(s): {', '.join(to_disconnect)}.")
    parts.append(f"Enabled {len(selected)} {tool['title']} action(s): {', '.join(selected)}.")
    logger.info(f"🎯 Smart selection for {tool['name']}: +{selected} -{to_disconnect}")
    return {
        "success": True,
        "actions_needed": True,
        "service": tool["name"],
        "added_actions": selected,
        "already_enabled_actions": service_enabled,
        "disconnected_actions": to_disconnect,
        "total_actions": total,
        "reasoning": reasoning,
        "message": " ".join(parts),
    }
