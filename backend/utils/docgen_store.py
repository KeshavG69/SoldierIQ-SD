"""Where a built document's spec lives between turns, so it can be edited, not rewritten.

Ported from PriceIQ (Mongo `chat_documents`) / Kroolo enterprise-fastapi (Redis).
SoldierIQ keeps it in Postgres, table `public.chat_documents`, one row per chat
session with a JSONB map of that session's documents:

    docs = {slug: {spec, next_id, version, label, link, object_key, errors,
                   updated_at, versions: [≤20 snapshots], stale?}}

The spec is the document's identity and the file is derived from it: block ids
live in the spec, survive a rebuild, and mean the same thing in a new sandbox a
week later. Versions are full spec snapshots, so undo is a rebuild of a spec
already known good.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from clients.postgres_client import get_postgres_client
from docgen.spec import DocumentSpec

_MAX_VERSIONS = 20
_MAX_DOCS = 20

_DDL = """
CREATE TABLE IF NOT EXISTS public.chat_documents (
    session_id TEXT PRIMARY KEY,
    docs JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""
_TABLE_READY = False


class VersionConflict(RuntimeError):
    """An edit named a version that is no longer current."""

    def __init__(self, slug: str, expected: int, actual: int):
        super().__init__(f"{slug} is at version {actual}, not {expected}; re-read it before editing")


class UnknownDocument(KeyError):
    def __init__(self, slug: str, known: List[str]):
        super().__init__(slug)
        self.slug, self.known = slug, known

    def __str__(self) -> str:
        known = ", ".join(self.known) or "none in this conversation"
        return f"no document called {self.slug!r}; known documents: {known}"


class StoreUnavailable(RuntimeError):
    """The store could not be read or written — NOT "there are no documents"."""


_locks: Dict[str, asyncio.Lock] = {}


async def _pool():
    global _TABLE_READY
    pool = await get_postgres_client().get_pool()
    if not _TABLE_READY:
        async with pool.acquire() as c:
            await c.execute(_DDL)
        _TABLE_READY = True
    return pool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _read(session_id: str) -> Dict[str, Any]:
    try:
        pool = await _pool()
        async with pool.acquire() as c:
            raw = await c.fetchval("SELECT docs FROM public.chat_documents WHERE session_id = $1",
                                   session_id)
    except Exception as exc:  # noqa: BLE001
        raise StoreUnavailable(f"the document store did not answer: {exc}") from exc
    # asyncpg returns JSONB as text (no codec registered in this app).
    docs = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return {"docs": docs or {}}


async def _write(session_id: str, state: Dict[str, Any]) -> None:
    try:
        pool = await _pool()
        async with pool.acquire() as c:
            await c.execute(
                "INSERT INTO public.chat_documents (session_id, docs, updated_at) "
                "VALUES ($1, $2::jsonb, now()) "
                "ON CONFLICT (session_id) DO UPDATE SET docs = EXCLUDED.docs, updated_at = now()",
                session_id, json.dumps(state["docs"], default=str),
            )
    except Exception as exc:  # noqa: BLE001
        raise StoreUnavailable(f"the document store did not accept the write: {exc}") from exc


@contextlib.asynccontextmanager
async def _locked(session_id: str):
    """Serialise read-modify-write on one session's documents within this process.

    The model runs tools in parallel; two writers each writing back what they read
    would lose an update.
    """
    if len(_locks) > 1024:
        _locks.clear()
    lock = _locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        yield


async def list_documents(session_id: str) -> List[Dict[str, Any]]:
    docs = (await _read(session_id))["docs"]
    return [
        {"slug": slug, "format": (d.get("spec") or {}).get("format"),
         "filename": (d.get("spec") or {}).get("filename"), "version": d.get("version", 1),
         "object_key": d.get("object_key"), "updated_at": d.get("updated_at")}
        for slug, d in sorted(docs.items(), key=lambda kv: kv[1].get("updated_at") or "")
    ]


async def get(session_id: str, slug: str) -> Dict[str, Any]:
    state = await _read(session_id)
    entry = state["docs"].get(slug)
    if entry is None:
        raise UnknownDocument(slug, sorted(state["docs"]))
    return entry


async def load_spec(session_id: str, slug: str) -> tuple[DocumentSpec, Dict[str, Any]]:
    entry = await get(session_id, slug)
    spec = DocumentSpec(**entry["spec"])
    spec.next_id = entry.get("next_id", spec.next_id)
    return spec, entry


async def save(
    session_id: str,
    slug: str,
    spec: DocumentSpec,
    *,
    label: str = "",
    base_version: Optional[int] = None,
    link: Optional[str] = None,
    object_key: Optional[str] = None,
    file_sha: Optional[str] = None,
    sandbox_id: Optional[str] = None,
    errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Store a new version of `slug`, refusing an edit built on a stale read."""
    async with _locked(session_id):
        state = await _read(session_id)
        entry = state["docs"].get(slug)
        if entry is not None and base_version is not None and entry.get("version") != base_version:
            raise VersionConflict(slug, base_version, entry.get("version", 0))
        version = (entry or {}).get("version", 0) + 1
        versions = list((entry or {}).get("versions") or [])
        if entry is not None:
            versions.append({"v": entry.get("version"), "ts": entry.get("updated_at"),
                             "label": entry.get("label", ""), "spec": entry.get("spec"),
                             "next_id": entry.get("next_id")})
            versions = versions[-_MAX_VERSIONS:]
        state["docs"][slug] = {
            "spec": spec.payload(),
            "next_id": spec.next_id,
            "version": version,
            "label": label,
            "spec_sha": spec.sha(),
            "file_sha": file_sha,
            "link": link,
            "object_key": object_key,
            "sandbox_id": sandbox_id,
            # This build's layout errors, so the next build can tell an error an edit
            # fixed from one no edit can reach.
            "errors": list(errors or []),
            "updated_at": _now(),
            "versions": versions,
        }
        if len(state["docs"]) > _MAX_DOCS:
            for old, _ in sorted(state["docs"].items(),
                                 key=lambda kv: kv[1].get("updated_at") or "")[:-_MAX_DOCS]:
                state["docs"].pop(old, None)
        await _write(session_id, state)
        return state["docs"][slug]


async def restore(session_id: str, slug: str, version: Optional[int] = None
                  ) -> tuple[DocumentSpec, int]:
    """The spec of an earlier version — the previous one by default (undo)."""
    entry = await get(session_id, slug)
    versions = entry.get("versions") or []
    if not versions:
        raise ValueError(f"{slug} has only one version; there is nothing to go back to")
    if version is None:
        snapshot = versions[-1]
    else:
        snapshot = next((s for s in versions if s.get("v") == version), None)
        if snapshot is None:
            have = ", ".join(str(s.get("v")) for s in versions)
            raise ValueError(f"{slug} has no version {version}; kept versions: {have}")
    spec = DocumentSpec(**snapshot["spec"])
    spec.next_id = snapshot.get("next_id", spec.next_id)
    return spec, snapshot.get("v")
