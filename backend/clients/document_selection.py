"""
Per-user document selection, persisted in Postgres.

The sidebar selection (which documents chat / studio tools are scoped to) used
to live only in the browser's localStorage, so it was lost on a cache reset, on
another device, or after signing out. One row per (organization_id, user_id)
now keeps it server-side.

`last_briefing_at` records when the user last got the login briefing, so the
next briefing can call out documents that are new or changed since then.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from clients.postgres_client import get_postgres_client

_TABLE_READY = False

_DDL = """
CREATE TABLE IF NOT EXISTS public.user_document_selections (
    organization_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    -- NULL until the user first saves a selection (a briefing can create the row first)
    document_ids TEXT[],
    last_briefing_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (organization_id, user_id)
);
-- The login briefing looks up documents added to the org since the last visit.
CREATE INDEX IF NOT EXISTS idx_documents_org_created
    ON public.documents (organization_id, created_at DESC);
"""


async def ensure_table() -> None:
    """Create the table on first use (idempotent) — no separate migration step."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        await c.execute(_DDL)
    _TABLE_READY = True


def _valid_uuids(ids: List[str]) -> List[uuid.UUID]:
    out = []
    for i in ids:
        try:
            out.append(uuid.UUID(str(i)))
        except (ValueError, TypeError):
            continue
    return out


async def get_selection(organization_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Saved selection, pruned to documents that still exist in this org.

    Returns None when the user has never saved a selection (so the client can
    keep whatever it already has instead of wiping it).
    """
    await ensure_table()
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        row = await c.fetchrow(
            """SELECT document_ids, last_briefing_at, updated_at
               FROM user_document_selections
               WHERE organization_id = $1 AND user_id = $2""",
            organization_id, user_id,
        )
        if not row or row["document_ids"] is None:
            return None

        saved = list(row["document_ids"])
        ids = _valid_uuids(saved)
        existing: set = set()
        if ids:
            rows = await c.fetch(
                "SELECT id FROM documents WHERE id = ANY($1::uuid[]) AND organization_id = $2",
                ids, uuid.UUID(organization_id),
            )
            existing = {str(r["id"]) for r in rows}

    # Keep the user's order; drop deleted / foreign documents.
    return {
        "document_ids": [d for d in saved if d in existing],
        "last_briefing_at": row["last_briefing_at"],
        "updated_at": row["updated_at"],
    }


async def save_selection(organization_id: str, user_id: str, document_ids: List[str]) -> None:
    await ensure_table()
    # De-dupe while keeping order.
    ids = list(dict.fromkeys(str(d) for d in document_ids))
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO user_document_selections (organization_id, user_id, document_ids, updated_at)
               VALUES ($1, $2, $3, now())
               ON CONFLICT (organization_id, user_id)
               DO UPDATE SET document_ids = EXCLUDED.document_ids, updated_at = now()""",
            organization_id, user_id, ids,
        )


async def mark_briefed(organization_id: str, user_id: str, at: datetime) -> None:
    """Record that the user got a briefing (creates the row if needed)."""
    await ensure_table()
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        await c.execute(
            """INSERT INTO user_document_selections (organization_id, user_id, last_briefing_at)
               VALUES ($1, $2, $3)
               ON CONFLICT (organization_id, user_id)
               DO UPDATE SET last_briefing_at = EXCLUDED.last_briefing_at""",
            organization_id, user_id, at,
        )
