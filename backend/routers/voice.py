"""Retrieval endpoint for the LiveKit voice-agent worker.

The worker runs outside this service (LiveKit Cloud), so it can't use a user's
Keycloak JWT. It authenticates with a shared secret instead and sends the
organization / document scope that the Next.js token route signed into the
participant metadata.

Search is deliberately identical to text chat: the same `create_knowledge_retriever`
tool (services/chat.py), the same arguments, and its output returned unchanged —
chunks, anchor entities and relation triples from the knowledge graph. The only
addition is a document_id -> file name map, because chunks carry only document ids.
"""

import asyncio
import hmac
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.logger import logger
from app.settings import settings
from clients.postgres_client import get_postgres_client
from utils.agno_tools import create_knowledge_retriever

router = APIRouter(prefix="/voice", tags=["voice"])

# Keep in sync with create_knowledge_retriever(num_documents=...) in services/chat.py.
CHAT_NUM_DOCUMENTS = 10


class VoiceSearchRequest(BaseModel):
    query: str
    organization_id: str
    document_ids: List[str] = Field(default_factory=list)


def _check_secret(provided: Optional[str]) -> None:
    expected = settings.VOICE_AGENT_SECRET
    if not expected:
        raise HTTPException(status_code=503, detail="Voice search is not configured")
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid voice agent secret")


async def _file_names(organization_id: str, document_ids: List[str]) -> Dict[str, str]:
    """document_id -> filename for the given docs (org-scoped, no raw_content)."""
    try:
        ids = [uuid.UUID(d) for d in document_ids if d]
    except ValueError:
        return {}
    if not ids:
        return {}
    try:
        pool = await get_postgres_client().get_pool()
        rows = await pool.fetch(
            "SELECT id, filename FROM documents WHERE organization_id = $1 AND id = ANY($2::uuid[])",
            uuid.UUID(organization_id),
            ids,
        )
    except Exception as e:
        # Names are only for spoken citations — never fail the search over them.
        logger.warning(f"voice_search: file name lookup failed: {e}")
        return {}
    return {str(r["id"]): r["filename"] for r in rows}


@router.post("/search")
async def voice_search(
    request: VoiceSearchRequest,
    x_voice_agent_secret: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _check_secret(x_voice_agent_secret)

    try:
        uuid.UUID(request.organization_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="organization_id must be a UUID")

    empty: Dict[str, Any] = {
        "chunks": [], "anchors": [], "triples": [], "count": 0,
        "query": request.query, "file_names": {},
    }
    if not request.document_ids:
        return empty

    # Exactly how routers/chat.py -> services/chat.py builds it: every org role may
    # query every org document (is_admin=True => no per-user RBAC pre-filter).
    retriever = create_knowledge_retriever(
        organization_id=request.organization_id,
        document_ids=request.document_ids,
        num_documents=CHAT_NUM_DOCUMENTS,
        is_admin=True,
    )
    # Search is scoped to the selected docs, so their names can be fetched in parallel.
    results, file_names = await asyncio.gather(
        retriever(request.query),
        _file_names(request.organization_id, request.document_ids),
    )
    if not results:
        return empty

    wrapper = results[0] if isinstance(results, list) else results
    if not isinstance(wrapper, dict):
        return empty

    chunks = wrapper.get("chunks") or []
    wrapper = {**wrapper, "file_names": file_names}

    logger.info(
        f"voice_search: org={request.organization_id} docs={len(request.document_ids)} "
        f"query={request.query[:60]!r} -> chunks={len(chunks)} "
        f"anchors={len(wrapper.get('anchors') or [])} triples={len(wrapper.get('triples') or [])}"
    )
    return wrapper
