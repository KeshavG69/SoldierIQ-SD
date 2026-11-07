"""
Hourly E2B sandbox reaper (Celery beat), ported from PriceIQ.

Paused sandboxes are kept by E2B indefinitely and billed for storage, so:
1. boxes unused for E2B_SANDBOX_MAX_IDLE_DAYS are killed (the manifest stays,
   so the chat keeps its owner and starts a fresh box next time);
2. boxes tagged with this database's store id that no manifest points at
   (lost races, failed manifest writes) are killed once they're an hour old.

Needs a beat process: `celery -A app.worker beat` (the worker alone never fires it).
"""

import asyncio

from app.logger import logger
from app.worker import celery_app


@celery_app.task(name="e2b.reap_sandboxes", time_limit=900, soft_time_limit=840)
def reap_sandboxes() -> dict:
    from utils.e2b_sandbox import is_configured, reap_idle_sandboxes, reap_orphan_sandboxes

    if not is_configured():
        return {"skipped": "E2B_API_KEY not set"}

    async def _run() -> dict:
        idle = await reap_idle_sandboxes()
        orphans = await reap_orphan_sandboxes()
        return {"idle_killed": idle, "orphans_killed": orphans}

    result = asyncio.run(_run())
    logger.info(f"[E2B] reaper: {result}")
    return result
