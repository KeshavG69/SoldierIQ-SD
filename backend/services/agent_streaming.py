"""
Agent Streaming Service
Handles streaming responses from Agno agents
"""

import time
from typing import Any, AsyncGenerator, Dict, Optional
from agno.agent import Agent
from agno.run.agent import RunEvent, RunOutput, RunOutputEvent
from app.logger import logger


def extract_text(content: Any) -> Optional[str]:
    """Extract text content from various payload formats"""
    if content is None:
        return None

    if isinstance(content, str):
        return content

    if isinstance(content, dict):
        if "text" in content and isinstance(content["text"], str):
            return content["text"]
        if "content" in content and isinstance(content["content"], str):
            return content["content"]
        return extract_text(content.get("value")) or extract_text(content.get("output"))

    return None


def sanitize_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure payload is JSON-serializable"""
    import json

    try:
        json.dumps(data)
        return data
    except TypeError:

        def _coerce(value: Any) -> Any:
            if isinstance(value, dict):
                return {k: _coerce(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_coerce(v) for v in value]
            try:
                json.dumps(value)
                return value
            except TypeError:
                return str(value)

        return {k: _coerce(v) for k, v in data.items()}


async def stream_agent_response(
    query: str,
    agent: Agent,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream Agno agent events as SSE-compatible payloads

    Args:
        query: User's query text
        agent: Agno Agent instance

    Yields:
        Dict: Event dictionaries for SSE streaming
    """
    if not query or not query.strip():
        yield {
            "event": "error",
            "data": {
                "error": "Query cannot be empty",
                "error_type": "ValidationError",
            }
        }
        return

    if agent is None:
        yield {
            "event": "error",
            "data": {
                "error": "Agent instance is required",
                "error_type": "ValidationError",
            }
        }
        return

    accumulated_content = []
    run_id = None
    start_time = time.monotonic()
    first_delta_emitted = False

    try:
        # Stream agent response
        response_stream = agent.arun(query, stream=True, stream_events=True)

        async for run_chunk in response_stream:
            payload: Dict[str, Any]

            # Convert run_chunk to dict
            if isinstance(run_chunk, RunOutputEvent):
                payload = run_chunk.to_dict()
            elif isinstance(run_chunk, RunOutput):
                payload = run_chunk.to_dict()
                payload.setdefault("event", RunEvent.run_completed.value)
            else:
                payload = {
                    "event": getattr(run_chunk, "event", RunEvent.run_content.value),
                    "content": str(run_chunk),
                }

            payload = sanitize_payload(payload)
            agno_event = payload.get("event", RunEvent.run_content.value)

            # Capture run_id
            if payload.get("run_id") and not run_id:
                run_id = payload.get("run_id")

            # Handle different event types
            if agno_event == RunEvent.run_started.value:
                run_id = payload.get("run_id")
                yield {
                    "event": "run.started",
                    "data": {
                        "run_id": run_id,
                        "session_id": payload.get("session_id"),
                    }
                }
                continue

            # Skip intermediate content (primary model output in hybrid mode with output_model)
            if agno_event == RunEvent.run_intermediate_content.value:
                logger.info(f"⏭️ Skipping intermediate content (primary model): {extract_text(payload.get('content'))[:50]}...")
                continue

            # Only stream final content (output_model response or single model response)
            if agno_event == RunEvent.run_content.value:
                delta_text = extract_text(payload.get("content"))
                if delta_text:
                    accumulated_content.append(delta_text)

                    if not first_delta_emitted:
                        first_delta_emitted = True
                        ttft_ms = (time.monotonic() - start_time) * 1000.0
                        logger.info(f"TTFT: {ttft_ms:.1f}ms, Run: {run_id}")

                    yield {
                        "event": "message.delta",
                        "data": {
                            "content": delta_text,
                            "run_id": run_id,
                        }
                    }
                continue

            if agno_event == RunEvent.tool_call_started.value:
                tool = payload.get("tool") or {}
                yield {
                    "event": "tool.started",
                    "data": {
                        "tool_name": tool.get("tool_name"),
                        "tool_args": tool.get("tool_args"),
                    }
                }
                continue

            if agno_event == RunEvent.tool_call_completed.value:
                tool = payload.get("tool") or {}
                yield {
                    "event": "tool.completed",
                    "data": {
                        "tool_name": tool.get("tool_name"),
                        "result": tool.get("result"),
                    }
                }
                continue

            if agno_event == RunEvent.run_error.value:
                yield {
                    "event": "error",
                    "data": {
                        "error": payload.get("error", "Unknown error"),
                        "error_type": payload.get("error_type", "AgentError"),
                    }
                }
                return

            if agno_event == RunEvent.run_completed.value:
                full_content = "".join(accumulated_content)
                yield {
                    "event": "message.completed",
                    "data": {
                        "content": full_content,
                        "run_id": run_id,
                    }
                }
                yield {
                    "event": "run.completed",
                    "data": {
                        "run_id": run_id,
                        "status": "success",
                    }
                }
                return

    except Exception as e:
        logger.error(f"Error in agent streaming: {str(e)}")
        yield {
            "event": "error",
            "data": {
                "error": str(e),
                "error_type": "StreamingError",
            }
        }
