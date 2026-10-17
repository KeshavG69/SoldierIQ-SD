"""
Copy chat sessions from MongoDB (agent_sessions) to Postgres (public.agent_sessions).

The chat agent now stores sessions in Postgres (clients/agent_memory.py). This
moves the existing history over so users keep their past conversations.

Idempotent: sessions already in Postgres are skipped (never overwritten), so it
is safe to run again. Mongo is only read, never modified.

    uv run python scripts/migrate_agent_sessions_to_postgres.py --dry-run
    uv run python scripts/migrate_agent_sessions_to_postgres.py
"""

import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import MongoClient  # noqa: E402

from app.settings import settings  # noqa: E402
from clients.agent_memory import SESSION_TABLE, get_agent_db  # noqa: E402
from clients.postgres_client import get_postgres_client  # noqa: E402

JSON_FIELDS = ("session_data", "agent_data", "team_data", "workflow_data", "metadata", "runs", "summary")
COLUMNS = ("session_id", "session_type", "agent_id", "team_id", "workflow_id", "user_id",
           *JSON_FIELDS, "created_at", "updated_at")


def _row(doc: dict) -> tuple:
    out = []
    for col in COLUMNS:
        v = doc.get(col)
        if col in JSON_FIELDS:
            # default=str covers ObjectId / datetime values nested in old docs.
            v = None if v is None else json.dumps(v, default=str)
        out.append(v)
    return tuple(out)


async def main(dry_run: bool) -> None:
    mongo = MongoClient(settings.MONGODB_URL)
    docs = list(mongo[settings.MONGODB_DATABASE]["agent_sessions"].find({}, {"_id": 0}))
    docs = [d for d in docs if d.get("session_id")]
    print(f"Mongo agent_sessions: {len(docs)} sessions, {len({d.get('user_id') for d in docs})} users")

    # Make sure the table exists with Agno's schema (sync; runs once).
    get_agent_db()._get_table("sessions", create_table_if_not_found=True)

    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as conn:
        existing = {r["session_id"] for r in await conn.fetch(f"SELECT session_id FROM {SESSION_TABLE}")}
        todo = [d for d in docs if d["session_id"] not in existing]
        missing_created = sum(1 for d in todo if d.get("created_at") is None)
        print(f"Postgres {SESSION_TABLE}: {len(existing)} already present")
        print(f"To copy: {len(todo)} (skipping {len(docs) - len(todo)} already there)")
        if missing_created:
            print(f"  {missing_created} have no created_at; will use updated_at or 0")

        if dry_run:
            print("Dry run — nothing written.")
            return

        for d in todo:
            if d.get("created_at") is None:
                d["created_at"] = d.get("updated_at") or 0
            if not d.get("session_type"):
                d["session_type"] = "agent"

        cols = ", ".join(COLUMNS)
        placeholders = ", ".join(
            f"${i}::jsonb" if c in JSON_FIELDS else f"${i}" for i, c in enumerate(COLUMNS, start=1)
        )
        sql = (f"INSERT INTO {SESSION_TABLE} ({cols}) VALUES ({placeholders}) "
               f"ON CONFLICT (session_id) DO NOTHING")
        async with conn.transaction():
            await conn.executemany(sql, [_row(d) for d in todo])

        total = await conn.fetchval(f"SELECT count(*) FROM {SESSION_TABLE}")
        print(f"Copied {len(todo)}. Postgres {SESSION_TABLE} now has {total} sessions.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report counts only, write nothing")
    asyncio.run(main(parser.parse_args().dry_run))
