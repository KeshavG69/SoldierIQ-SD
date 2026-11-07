"""Exa web search for the chat agent (agno's built-in ExaTools).

Configured like PriceIQ's get_web_search_tool, without its govcon domain list:
SoldierIQ users search doctrine, news and open-source information broadly.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from agno.tools.exa import ExaTools

from app.logger import logger
from app.settings import settings


@lru_cache(maxsize=1)
def get_web_search_tool(num_results: int = 6, text_length_limit: int = 2000) -> Optional[ExaTools]:
    """A cached ExaTools, or None when EXA_API_KEY is not set.

    - search_exa + get_contents only: raw results the agent cites, not Exa's own
      synthesis (exa_answer) or find_similar.
    - livecrawl="always" for fresh pages (Exa's index can be stale).
    - A short text cap per result keeps the model's context small.
    """
    if not settings.EXA_API_KEY:
        logger.warning("[web_search] EXA_API_KEY not set — web search disabled")
        return None
    try:
        tool = ExaTools(
            api_key=settings.EXA_API_KEY,
            num_results=num_results,
            enable_search=True,
            enable_get_contents=True,
            enable_find_similar=False,
            enable_answer=False,
            text=True,
            text_length_limit=text_length_limit,
            summary=False,
            livecrawl="always",
        )
        logger.info(f"[web_search] Exa initialized (num_results={num_results})")
        return tool
    except Exception as e:  # noqa: BLE001
        logger.error(f"[web_search] failed to init ExaTools: {e}", exc_info=True)
        return None
