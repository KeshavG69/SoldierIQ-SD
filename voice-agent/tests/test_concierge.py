"""Behaviour tests for the avatar concierge (text in, judged text out — no room, no avatar).

Needs OPENROUTER_API_KEY (the agent's LLM doubles as the judge). Run: uv run pytest
"""

import pytest
from livekit.agents import AgentSession
from livekit.plugins import openai

from concierge import ConciergeAgent
from settings import settings

pytestmark = pytest.mark.skipif(not settings.OPENROUTER_API_KEY, reason="OPENROUTER_API_KEY not set")


def _llm() -> openai.LLM:
    return openai.LLM.with_openrouter(model=settings.VOICE_LLM_MODEL, api_key=settings.OPENROUTER_API_KEY)


async def _reply_matches(user_input: str, intent: str) -> None:
    async with _llm() as llm, AgentSession(llm=llm) as session:
        await session.start(ConciergeAgent())
        result = await session.run(user_input=user_input)
        await result.expect.next_event().is_message(role="assistant").judge(llm, intent=intent)
        result.expect.no_more_events()


async def test_introduces_itself_and_offers_help() -> None:
    await _reply_matches(
        "Hi, what can you do?",
        "Briefly says it helps people use the SoldierIQ app and offers to help. "
        "Short and spoken-style: no markdown, bullet points or lists.",
    )


async def test_points_to_where_documents_are_uploaded() -> None:
    await _reply_matches(
        "How do I add a document?",
        "Says documents are added from the left sidebar (upload, Google Drive or YouTube).",
    )


async def test_does_not_invent_document_contents() -> None:
    await _reply_matches(
        "What does my supply contract say about payment terms?",
        "Does not claim what the payment terms are (referring to the contract by name is fine). "
        "Explains it can't read the user's documents and suggests selecting them in the sidebar "
        "and asking there (in chat; also mentioning the voice/mic button is optional).",
    )


async def test_escalates_what_it_cannot_do() -> None:
    await _reply_matches(
        "Please delete my account for me.",
        "Says it cannot do that itself and points the user to New ticket or Book call "
        "(or the SoldierIQ team) for help.",
    )
