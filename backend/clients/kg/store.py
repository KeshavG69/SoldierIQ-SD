"""
FalkorDB connection + index management for the KG revamp.

One graph per organization ("org_<id>"), matching the deployed convention.
Uses the DDL vector-index syntax that this FalkorDB actually supports (the
db.idx.vector.createNodeIndex procedure is NOT registered — see the earlier
graphrag_client fix).
"""
from __future__ import annotations

import time
from typing import Any, Dict

import falkordb

from app.logger import logger
from app.settings import settings

_connections: Dict[str, Any] = {}
_last_used: Dict[str, float] = {}

# Railway's TCP proxy silently drops idle connections. A query written to such a
# socket is never acknowledged, and with no socket timeout it blocks forever (seen
# as the first search after a few idle minutes hanging). So: open a fresh client
# when the cached one has been idle this long, and bound every socket operation
# as a backstop so nothing can hang indefinitely.
_IDLE_RECYCLE_S = 120
_SOCKET_TIMEOUT_S = 300


def graph_name(organization_id: str) -> str:
    return f"org_{organization_id}"


def get_graph(organization_id: str):
    name = graph_name(organization_id)
    now = time.monotonic()
    if name in _connections and now - _last_used.get(name, now) > _IDLE_RECYCLE_S:
        logger.info(f"[kg-store] recycling FalkorDB client for {name} after idle period")
        del _connections[name]
    if name not in _connections:
        db = falkordb.FalkorDB(
            host=settings.GRAPH_DATABASE_URL,
            port=settings.GRAPH_DATABASE_PORT,
            username=settings.GRAPH_DATABASE_USERNAME or None,
            password=settings.GRAPH_DATABASE_PASSWORD or None,
            ssl=settings.GRAPH_DATABASE_SSL,
            socket_timeout=_SOCKET_TIMEOUT_S,
            socket_connect_timeout=10,
        )
        _connections[name] = db.select_graph(name)
    _last_used[name] = now
    return _connections[name]


def ensure_indexes(g) -> None:
    """Idempotently create the vector + range indexes the two-layer graph needs."""
    # Vector index on Chunk.embedding (DDL form; dimension inlined, params rejected).
    try:
        g.query(
            f"CREATE VECTOR INDEX FOR (c:Chunk) ON (c.embedding) "
            f"OPTIONS {{dimension: {int(settings.EMBEDDING_DIM)}, "
            f"similarityFunction: 'cosine'}}"
        )
        logger.info("Created Chunk.embedding vector index")
    except Exception as e:
        msg = str(e).lower()
        if "already" not in msg and "exist" not in msg:
            logger.warning(f"Vector index creation failed: {e}")

    # Range indexes for fast lookups / joins / RBAC traversal.
    for label, prop in [
        ("Document", "document_id"),
        ("Chunk", "document_id"),
        ("Chunk", "id"),
        ("Entity", "name"),
        ("User", "email"),
    ]:
        try:
            g.query(f"CREATE INDEX ON :{label}({prop})")
        except Exception:
            pass
