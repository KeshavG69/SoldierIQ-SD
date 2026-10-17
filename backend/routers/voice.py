"""Voice endpoints.

POST /api/voice/search       Retrieval for the LiveKit voice-agent worker (below).
POST /api/voice/transcribe   Chat mic-button dictation: one short clip → text.

Retrieval endpoint for the LiveKit voice-agent worker.

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
import base64
import hmac
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.logger import logger
from app.settings import settings
from clients.postgres_client import get_postgres_client
from orgs.dependencies import get_current_context
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


# ------------------------------------------------------------------ dictation
# The browser does the "live" part: it cuts speech into short segments at
# pauses and re-sends the segment in progress about once a second, so text
# appears while the user talks. OpenRouter's STT endpoint is request/response
# only (no streaming), so near-live is the closest it can get.
OPENROUTER_STT_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
# Segments are a few seconds of 16 kHz mono PCM (~32 KB/s); anything near this
# is a bug or abuse, not dictation.
MAX_AUDIO_BYTES = 10 * 1024 * 1024
_FORMATS = {"wav", "webm", "ogg", "mp3", "m4a", "mp4", "flac", "aac"}

_stt_client: Optional[httpx.AsyncClient] = None


def _stt_http() -> httpx.AsyncClient:
    # One pooled client: dictation fires a request every ~second, so reusing
    # the TLS connection to OpenRouter matters.
    global _stt_client
    if _stt_client is None:
        _stt_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
    return _stt_client


@router.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    audio_format: str = Form("wav"),
    language: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_context),
) -> Dict[str, Any]:
    if not settings.OPENROUTER_API_KEY:
        raise HTTPException(status_code=503, detail="Speech-to-text is not configured")
    fmt = (audio_format or "wav").lower().strip()
    if fmt not in _FORMATS:
        raise HTTPException(status_code=400, detail=f"Unsupported audio format: {fmt}")

    data = await audio.read()
    if not data:
        return {"text": ""}
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio clip too large")

    body: Dict[str, Any] = {
        "model": settings.VOICE_STT_MODEL,
        "input_audio": {"data": base64.b64encode(data).decode("ascii"), "format": fmt},
    }
    if language:
        body["language"] = language

    try:
        resp = await _stt_http().post(
            OPENROUTER_STT_URL,
            headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
            json=body,
        )
    except httpx.HTTPError as e:
        logger.warning(f"STT request failed: {e}")
        raise HTTPException(status_code=502, detail="Speech-to-text service unreachable")

    if resp.status_code != 200:
        logger.warning(f"STT {resp.status_code}: {resp.text[:300]}")
        raise HTTPException(status_code=502, detail="Speech-to-text failed")

    return {"text": (resp.json().get("text") or "").strip()}
