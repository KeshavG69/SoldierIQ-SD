"""
Simple Chat API Endpoint
Just takes a query and returns a streaming LLM response using Agno
"""

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
from agno.agent import Agent
from clients.ultimate_llm import get_llm_agno
from services.agent_streaming import stream_agent_response
from utils.streaming import create_sse_event_stream
from app.logger import logger

router = APIRouter(tags=["simple-chat"])


class SimpleQuery(BaseModel):
    """Request model for simple chat"""
    query: str
    model: Optional[str] = "google/gemini-2.5-pro"


@router.post("/simple-chat")
async def simple_chat(request: SimpleQuery):
    """
    Simple chat endpoint - takes a query and returns a streaming LLM response

    Args:
        request: SimpleQuery with query string and optional model

    Returns:
        StreamingResponse with SSE events
    """
    try:
        if not request.query or request.query.strip() == "":
            raise HTTPException(
                status_code=400,
                detail="Query is required and cannot be empty"
            )

        logger.info(f"Simple chat query: '{request.query[:50]}...'")

        # Get LLM
        llm = get_llm_agno(model=request.model, provider="openrouter")

        # Create simple agent (no tools, no knowledge base)
        agent = Agent(
            name="Simple Assistant",
            model=llm,
            instructions=[
                "You are a helpful AI assistant.",
                "Provide clear, concise, and accurate responses.",
                "Be friendly and professional."
            ],
            markdown=True,
        )

        # SSE headers
        headers = {
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Vary": "Accept",
        }

        # Stream response
        async def sse_stream():
            events = stream_agent_response(request.query, agent)
            async for chunk in create_sse_event_stream(events):
                yield chunk

        return StreamingResponse(
            sse_stream(),
            media_type="text/event-stream",
            headers=headers
        )

    except Exception as e:
        logger.error(f"Simple chat error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")
