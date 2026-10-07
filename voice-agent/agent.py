"""LiveKit voice agent entrypoint.

Runs as a LiveKit Cloud agent worker. Connects to rooms, reads the participant's
metadata (user_id, organization_id, document_ids, file_names) to scope retrieval,
and starts an AgentSession wired up with:
  - LLM:    GPT-6 Luna via OpenRouter (settings.VOICE_LLM_MODEL)
  - STT:    Deepgram Nova-3    (via LiveKit Inference)
  - TTS:    Cartesia Sonic-2   (via LiveKit Inference)
  - VAD:    Silero
  - Turn detection: LiveKit multilingual model
  - Noise cancellation: LiveKit Cloud BVC

Retrieval is delegated to this repo's backend (POST /api/voice/search, the same
knowledge-graph search as text chat) via HTTP — see retriever.py.
"""

from __future__ import annotations

import asyncio
import json
import logging

from livekit.agents import (
    AgentSession,
    JobContext,
    RoomInputOptions,
    WorkerOptions,
    cli,
)
from livekit.plugins import noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from prompts import build_instructions
from settings import settings
from tools import KnowledgeAgent

logger = logging.getLogger("voice-agent")


def _parse_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        logger.warning("Participant metadata was not a JSON object: %r", raw)
    except json.JSONDecodeError:
        logger.warning("Participant metadata was not valid JSON: %r", raw)
    return {}


async def _wait_for_metadata(ctx: JobContext, timeout: float = 3.0) -> dict:
    """Try to read participant metadata, but don't block forever.

    In production a participant joins with metadata set via the token. In
    console/dev mode there may be no remote participant — we fall back to
    VOICE_DEV_METADATA (JSON, local testing only) or {} (tool will ask the user
    to select docs).
    """
    try:
        participant = await asyncio.wait_for(ctx.wait_for_participant(), timeout=timeout)
        return _parse_metadata(participant.metadata)
    except asyncio.TimeoutError:
        if settings.VOICE_DEV_METADATA:
            logger.info("No participant joined within %.1fs — using VOICE_DEV_METADATA", timeout)
            return _parse_metadata(settings.VOICE_DEV_METADATA)
        logger.info("No participant joined within %.1fs — running with empty metadata", timeout)
        return {}



async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    metadata = await _wait_for_metadata(ctx)

    logger.info(
        "Voice agent starting for user=%s org=%s docs=%s",
        metadata.get("user_id"),
        metadata.get("organization_id"),
        len(metadata.get("document_ids") or []),
    )

    session = AgentSession(
        llm=openai.LLM.with_openrouter(
            model=settings.VOICE_LLM_MODEL,
            api_key=settings.OPENROUTER_API_KEY,
        ),
        stt="deepgram/nova-3",
        tts="cartesia/sonic-2",
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
        userdata=metadata,
    )

    agent = KnowledgeAgent(
        instructions=build_instructions(
            document_ids=metadata.get("document_ids"),
            file_names=metadata.get("file_names"),
        )
    )

    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    if not metadata.get("document_ids"):
        greeting = (
            "Hi — I don't see any documents selected yet. "
            "Please pick some from the sidebar and then ask me anything about them."
        )
    else:
        greeting = "Hi, I'm ready. What would you like to know about your documents?"
    await session.generate_reply(instructions=f"Say exactly: {greeting!r}")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
