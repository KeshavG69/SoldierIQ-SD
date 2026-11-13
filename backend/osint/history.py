"""A small Redis-backed history so tools can answer "what happened before" and
"is this unusual". Filled by the Celery collector (tasks/osint_tasks.py) every
15 minutes. Events are kept for 180 days.

Keys (under osint:v1:):
  hist:events            sorted set, score = epoch seconds, member = event JSON
  hist:event_ids         set of stored event ids (dedupe)
  hist:mil:<theater>     sorted set of military-aircraft counts (score = epoch)
  hist:count:<iso2>      hash hour-bucket -> GDELT conflict-event count
  hist:risk:<iso2>       hash YYYY-MM-DD -> daily country-risk JSON
"""

from __future__ import annotations

import json
import time
from typing import Iterable, Optional

from osint.core import CACHE_PREFIX, redis_or_none
from osint.sources.news import tokens

RETENTION_S = 180 * 86400
EVENTS = CACHE_PREFIX + "hist:events"
EVENT_IDS = CACHE_PREFIX + "hist:event_ids"


class HistoryUnavailable(Exception):
    pass


async def _r():
    r = await redis_or_none()
    if r is None:
        raise HistoryUnavailable("Redis is not reachable, so history is unavailable")
    return r


async def add_events(events: Iterable[dict]) -> int:
    """Store events with fields id, ts (epoch), domain, title, and optional country/lat/lon/url/source."""
    r = await _r()
    added = 0
    for e in events:
        if not e.get("id") or not e.get("ts"):
            continue
        if await r.sadd(EVENT_IDS, e["id"]):
            await r.zadd(EVENTS, {json.dumps(e, default=str, ensure_ascii=False): float(e["ts"])})
            added += 1
    cutoff = time.time() - RETENTION_S
    await r.zremrangebyscore(EVENTS, 0, cutoff)
    return added


async def query_events(since: float, until: Optional[float] = None, country: Optional[str] = None,
                       domain: Optional[str] = None, limit: int = 200) -> list[dict]:
    r = await _r()
    raw = await r.zrevrangebyscore(EVENTS, until or "+inf", since, start=0, num=5000)
    out = []
    for item in raw:
        e = json.loads(item)
        if country and (e.get("country") or "").upper() != country.upper():
            continue
        if domain and e.get("domain") != domain:
            continue
        out.append(e)
        if len(out) >= limit:
            break
    return out


async def search_events(query: str, since: float, country: Optional[str] = None, limit: int = 20) -> list[dict]:
    """Keyword-overlap search over stored event titles."""
    q = tokens(query)
    if not q:
        return []
    events = await query_events(since, country=country, limit=5000)
    scored = []
    for e in events:
        t = tokens(f"{e.get('title', '')} {e.get('place', '')} {e.get('country_name', '')}")
        overlap = len(q & t)
        if overlap:
            scored.append((overlap / len(q), e))
    scored.sort(key=lambda x: (-x[0], -float(x[1].get("ts") or 0)))
    return [{**e, "match": round(s, 2)} for s, e in scored[:limit]]


async def record_military(theater: str, count: int, ts: Optional[float] = None) -> None:
    r = await _r()
    ts = ts or time.time()
    key = CACHE_PREFIX + f"hist:mil:{theater}"
    await r.zadd(key, {f"{int(ts)}:{count}": ts})
    await r.zremrangebyscore(key, 0, ts - 60 * 86400)


async def military_series(theater: str, since: float) -> list[tuple[float, int]]:
    r = await _r()
    raw = await r.zrangebyscore(CACHE_PREFIX + f"hist:mil:{theater}", since, "+inf")
    out = []
    for m in raw:
        t, c = m.split(":")
        out.append((float(t), int(c)))
    return out


async def bump_counts(counts: dict[str, int], hour_bucket: int) -> None:
    r = await _r()
    for iso2, n in counts.items():
        key = CACHE_PREFIX + f"hist:count:{iso2}"
        await r.hincrby(key, str(hour_bucket), n)
        await r.expire(key, 60 * 86400)


async def count_series(iso2: str) -> dict[int, int]:
    r = await _r()
    raw = await r.hgetall(CACHE_PREFIX + f"hist:count:{iso2}")
    return {int(k): int(v) for k, v in raw.items()}


async def record_risk(iso2: str, day: str, payload: dict) -> None:
    r = await _r()
    key = CACHE_PREFIX + f"hist:risk:{iso2}"
    await r.hset(key, day, json.dumps(payload))
    await r.expire(key, 400 * 86400)


async def risk_history(iso2: str) -> dict[str, dict]:
    r = await _r()
    raw = await r.hgetall(CACHE_PREFIX + f"hist:risk:{iso2}")
    return {k: json.loads(v) for k, v in sorted(raw.items())}
