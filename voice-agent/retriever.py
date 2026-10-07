"""Knowledge search for the voice agent — delegated to the SoldierIQ backend.

The backend's POST /api/voice/search runs the same knowledge-graph retrieval the
text chat agent uses (vector seed + entity anchors + relation traversal + adjacent
chunks) and returns {chunks, anchors, triples, count, query, file_names}. The worker
no longer talks to a vector database itself, so voice and chat can't drift apart.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from settings import settings

logger = logging.getLogger("voice-agent.retriever")


class SearchUnavailable(Exception):
    """The backend search could not be reached or refused the request."""


async def search(
    query: str,
    organization_id: str,
    document_ids: list[str],
) -> dict[str, Any]:
    """Run the backend knowledge search for the selected documents."""
    if not query.strip() or not document_ids:
        return {}
    if not settings.BACKEND_URL or not settings.VOICE_AGENT_SECRET:
        raise SearchUnavailable("BACKEND_URL / VOICE_AGENT_SECRET are not configured")

    url = settings.BACKEND_URL.rstrip("/") + "/api/voice/search"
    timeout = aiohttp.ClientTimeout(total=settings.VOICE_SEARCH_TIMEOUT_S)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json={
                    "query": query,
                    "organization_id": organization_id,
                    "document_ids": document_ids,
                },
                headers={"X-Voice-Agent-Secret": settings.VOICE_AGENT_SECRET},
            ) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:200]
                    raise SearchUnavailable(f"backend returned {resp.status}: {body}")
                return await resp.json()
    except (aiohttp.ClientError, TimeoutError) as e:
        raise SearchUnavailable(f"backend request failed: {e!r}") from e
