"""
Voice dictation — speech-to-text for the chat mic button.

POST /api/voice/transcribe   One short audio clip (WAV/WebM/…) → {"text": ...}

The browser does the "live" part: it cuts speech into short segments at
pauses and re-sends the segment in progress about once a second, so text
appears while the user talks. OpenRouter's STT endpoint is request/response
only (no streaming), so near-live is the closest it can get.

Model: Deepgram Nova-3 via OpenRouter — the provider Claude Code's own voice
dictation uses (`stt_provider=deepgram-nova3`). Override with VOICE_STT_MODEL.
"""
from __future__ import annotations

import base64
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.logger import logger
from app.settings import settings
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/voice", tags=["voice"])

OPENROUTER_STT_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
# Segments are a few seconds of 16 kHz mono PCM (~32 KB/s); anything near this
# is a bug or abuse, not dictation.
MAX_AUDIO_BYTES = 10 * 1024 * 1024
_FORMATS = {"wav", "webm", "ogg", "mp3", "m4a", "mp4", "flac", "aac"}

_client: Optional[httpx.AsyncClient] = None


def _http() -> httpx.AsyncClient:
    # One pooled client: dictation fires a request every ~second, so reusing
    # the TLS connection to OpenRouter matters.
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0))
    return _client


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
        resp = await _http().post(
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
