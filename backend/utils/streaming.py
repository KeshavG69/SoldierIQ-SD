"""
Streaming Utilities
SSE (Server-Sent Events) streaming helpers
"""

import asyncio
import json
from contextlib import suppress
from typing import Any, AsyncIterator, Dict


def create_sse_event_stream(
    events: AsyncIterator[Dict[str, Any]],
) -> AsyncIterator[str]:
    """
    Convert structured events into SSE frames with keepalive heartbeats

    Args:
        events: Async iterator of event dictionaries

    Yields:
        str: SSE formatted strings
    """

    async def _run():
        iterator = events.__aiter__()
        pending = asyncio.create_task(iterator.__anext__())
        event_id = 0
        keepalive_interval = 300  # seconds

        try:
            while True:
                try:
                    # Wait for next event with timeout for keepalive
                    event = await asyncio.wait_for(pending, timeout=keepalive_interval)
                except asyncio.TimeoutError:
                    # Send keepalive comment to maintain connection
                    yield ": keepalive\n\n"
                    # Continue waiting for the actual event
                    continue
                except StopAsyncIteration:
                    yield "data: [DONE]\n\n"
                    break
                except Exception as exc:
                    event_id += 1
                    fallback = {
                        "event": "error",
                        "error": str(exc),
                        "error_type": "StreamingError",
                    }
                    data = json.dumps(fallback, ensure_ascii=False, default=str)
                    yield f"id: {event_id}\nevent: error\ndata: {data}\n\n"
                    yield "data: [DONE]\n\n"
                    break
                else:
                    event_id += 1
                    payload = {k: v for k, v in event.items() if k != "event"}
                    data = json.dumps(payload, ensure_ascii=False, default=str)
                    event_name = event.get("event", "message.delta")
                    yield f"id: {event_id}\nevent: {event_name}\ndata: {data}\n\n"
                    pending = asyncio.create_task(iterator.__anext__())
        finally:
            if not pending.done():
                pending.cancel()
                with suppress(asyncio.CancelledError):
                    await pending
            else:
                with suppress(asyncio.CancelledError, StopAsyncIteration):
                    pending.result()

    return _run()
