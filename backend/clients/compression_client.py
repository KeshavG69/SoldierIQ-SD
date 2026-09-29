"""
Shared Agno CompressionManager for the chat agent.

Ported from enterprise-fastapi/services/clients/compression_client.py. When a
run's context crosses the token limit, Agno asks a fast model to summarize the
bulky tool results (Gmail fetches, knowledge-base chunks, …) instead of
sending them to the main model verbatim.

Same 750k limit as enterprise: SoldierIQ's default chat model,
anthropic/claude-sonnet-5.5, is listed at a 1M-token context on OpenRouter (the
compression model, gemini-3-flash-preview, has ~1.05M).
"""
import threading

from agno.compression.manager import CompressionManager

from app.logger import logger
from clients.ultimate_llm import get_llm_agno

COMPRESSION_MODEL = "google/gemini-3-flash-preview"
COMPRESS_TOKEN_LIMIT = 750_000

_compression_manager: CompressionManager = None
_compression_manager_lock = threading.Lock()


def get_compression_manager() -> CompressionManager:
    global _compression_manager

    if _compression_manager is not None:
        return _compression_manager

    with _compression_manager_lock:
        if _compression_manager is not None:
            return _compression_manager

        _compression_manager = CompressionManager(
            model=get_llm_agno(model=COMPRESSION_MODEL, provider="openrouter"),
            compress_token_limit=COMPRESS_TOKEN_LIMIT,
        )
        logger.info(
            f"Initialized CompressionManager with {COMPRESS_TOKEN_LIMIT:,} token limit using {COMPRESSION_MODEL}"
        )
        return _compression_manager
