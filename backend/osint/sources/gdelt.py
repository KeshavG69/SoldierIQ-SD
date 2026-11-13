"""GDELT 2.0: the 15-minute event export and the DOC 2.0 article search.

GDELT events are machine-coded from news, so they are signals about what is
being reported, not verified incidents. The DOC API allows about one request
every 5 seconds per IP, so calls are serialized and cached.
"""

from __future__ import annotations

import asyncio
import csv
import io
import time
import zipfile
from datetime import datetime, timedelta, timezone

from osint.core import SourceError, cached, get_bytes, get_text

LASTUPDATE_URL = "https://data.gdeltproject.org/gdeltv2/lastupdate.txt"
EXPORT_URL = "https://data.gdeltproject.org/gdeltv2/{stamp}.export.CSV.zip"
DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# CAMEO root codes: 14 protest, 15 force posture, 17 coerce, 18 assault, 19 fight, 20 mass violence
ROOT_LABELS = {
    "14": "protest", "15": "military_posture", "17": "coercion", "18": "assault",
    "19": "armed_clash", "20": "mass_violence",
}
CONFLICT_ROOTS = {"18", "19", "20"}

csv.field_size_limit(10_000_000)


def _f(row: list[str], i: int) -> str:
    return row[i] if i < len(row) else ""


def _parse_export(raw: bytes) -> list[dict]:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        name = zf.namelist()[0]
        text = zf.read(name).decode("utf-8", errors="replace")
    out = []
    for row in csv.reader(io.StringIO(text), delimiter="\t"):
        root = _f(row, 28)
        if root not in ROOT_LABELS:
            continue
        try:
            lat, lon = float(_f(row, 56)), float(_f(row, 57))
        except ValueError:
            continue
        geo_type = _f(row, 51)
        out.append({
            "id": f"gdelt:{_f(row, 0)}",
            "date_added": _f(row, 59),
            "root_code": root,
            "category": ROOT_LABELS[root],
            "event_code": _f(row, 26),
            "actor1": _f(row, 6) or None,
            "actor1_country": _f(row, 7) or None,
            "actor2": _f(row, 16) or None,
            "actor2_country": _f(row, 17) or None,
            "goldstein": float(_f(row, 30) or 0),
            "num_sources": int(_f(row, 32) or 0),
            "num_articles": int(_f(row, 33) or 0),
            "tone": round(float(_f(row, 34) or 0), 2),
            "place": _f(row, 52),
            "country_fips": _f(row, 53),
            "precision": {"1": "country", "2": "us_state", "3": "city", "4": "world_city", "5": "world_state"}.get(geo_type, "unknown"),
            "lat": lat,
            "lon": lon,
            "source_url": _f(row, 60),
        })
    return out


def _stamps(hours: float) -> list[str]:
    now = datetime.now(timezone.utc) - timedelta(minutes=15)
    now = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    n = max(1, int(hours * 4))
    return [(now - timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in range(n)]


async def _export_file(stamp: str) -> list[dict]:
    async def fetch():
        raw = await get_bytes(EXPORT_URL.format(stamp=stamp), timeout=40)
        return _parse_export(raw)

    value, _ = await cached(f"gdelt:export:{stamp}", 3 * 3600, fetch)
    return value


async def recent_events(hours: float = 3) -> tuple[list[dict], str]:
    """Protest/force/conflict-coded GDELT events from the last `hours` (max 24)."""
    hours = max(0.25, min(hours, 24))
    stamps = _stamps(hours)
    results = await asyncio.gather(*(_export_file(s) for s in stamps), return_exceptions=True)
    events, failures = [], 0
    for r in results:
        if isinstance(r, Exception):
            failures += 1
        else:
            events.extend(r)
    if failures == len(stamps):
        raise SourceError("GDELT export files unavailable")
    return events, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_doc_lock = asyncio.Lock()
_doc_last = 0.0


async def doc_search(query: str, mode: str = "artlist", timespan: str = "24h", max_records: int = 75,
                     extra: str = "") -> tuple[dict, str]:
    """GDELT DOC 2.0 search. mode: artlist | timelinevolraw | timelinetone | tonechart."""
    q = query.strip()
    if extra:
        q = f"{q} {extra}"
    params = {"query": q, "mode": mode, "format": "json", "timespan": timespan,
              "maxrecords": max(1, min(int(max_records), 250)), "sort": "datedesc"}

    async def fetch():
        global _doc_last
        async with _doc_lock:
            text = None
            for attempt in range(2):
                wait = (6.0 if attempt == 0 else 10.0) - (time.monotonic() - _doc_last)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    text = await get_text(DOC_URL, params=params, timeout=45)
                    break
                except SourceError as e:
                    # GDELT allows ~1 request per 5 s per IP; back off once on 429.
                    if "429" not in str(e) or attempt == 1:
                        raise
                finally:
                    _doc_last = time.monotonic()
        text = text.strip()
        if not text.startswith("{"):
            # GDELT answers malformed queries with a plain-text message.
            raise SourceError(f"GDELT DOC rejected the query: {text[:120]}")
        import json
        return json.loads(text)

    key = f"gdelt:doc:{mode}:{timespan}:{params['maxrecords']}:{q.lower()}"
    return await cached(key, 900, fetch)
