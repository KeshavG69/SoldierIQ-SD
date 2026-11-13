"""History: intel timeline, history search, similar events, temporal anomalies.

These read the event store that tasks/osint_tasks.py fills every 15 minutes, so
they only know what happened after the collector started.
"""

from __future__ import annotations

import time
from typing import Optional

from osint import geo, history
from osint.core import UNTRUSTED_NOTE, Result, iso, unavailable
from osint.registry import osint_tool
from osint.sources import news

STORE_NOTE = ("History comes from SoldierIQ's own collector (every 15 minutes, kept 180 days). "
              "A quiet period before collection started is empty, not calm.")


def _store_source(r: Result) -> None:
    r.source("SoldierIQ event history (Redis)", "", iso(), ok=True)


@osint_tool(group="history", tier=1)
async def get_intel_timeline(country: Optional[str] = None, domain: Optional[str] = None, days: int = 7,
                             limit: int = 60) -> str:
    """Reverse-chronological timeline of recorded intelligence events (strike reports, corroborated news stories,
    major conflict events, alerts) for a country and/or domain.

    Args:
        country: Optional country name or ISO code.
        domain: Optional domain: strike, conflict, news, military, alert.
        days: Look-back in days (1-180, default 7).
        limit: Maximum events (default 60).
    """
    c = geo.country(country) if country else None
    if country and not c:
        return unavailable("get_intel_timeline", f"Unknown country {country!r}")
    if not (c or domain):
        return unavailable("get_intel_timeline", "Give a country or a domain")
    r = Result("get_intel_timeline")
    try:
        events = await history.query_events(time.time() - max(1, min(int(days), 180)) * 86400,
                                            country=c["iso2"] if c else None, domain=domain, limit=max(1, min(limit, 200)))
    except history.HistoryUnavailable as e:
        return unavailable("get_intel_timeline", str(e))
    _store_source(r)
    r.data = {"country": c["name"] if c else None, "domain": domain, "days": days, "events": events}
    r.notes += [STORE_NOTE, UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="history", tier=1)
async def search_intel_history(query: str, country: Optional[str] = None, days: int = 180, limit: int = 20) -> str:
    """Search past recorded events by keywords (place, actor, weapon, topic), e.g. "drone strike Erbil" or
    "tanker mine Hormuz". Ranked by keyword overlap, newest first on ties.

    Args:
        query: Keywords to search for.
        country: Optional country name or ISO code to restrict results.
        days: How far back (1-180, default 180).
        limit: Maximum results (default 20).
    """
    c = geo.country(country) if country else None
    r = Result("search_intel_history")
    try:
        hits = await history.search_events(query, time.time() - max(1, min(int(days), 180)) * 86400,
                                           country=c["iso2"] if c else None, limit=max(1, min(limit, 50)))
    except history.HistoryUnavailable as e:
        return unavailable("search_intel_history", str(e))
    _store_source(r)
    r.data = {"query": query, "results": hits}
    r.notes += [STORE_NOTE, UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="history", tier=1)
async def get_similar_events(situation: str, country: Optional[str] = None, limit: int = 10) -> str:
    """Historical precedents for a described situation: past recorded events most similar to it (keyword overlap,
    same country preferred), so an analyst can see what happened the last times something like this occurred.

    Args:
        situation: A short description, e.g. "IRGC claims strike on US radar in Bahrain".
        country: Optional country to prefer.
        limit: Maximum precedents (default 10).
    """
    c = geo.country(country) if country else None
    r = Result("get_similar_events")
    try:
        hits = await history.search_events(situation, time.time() - 180 * 86400, country=None, limit=200)
    except history.HistoryUnavailable as e:
        return unavailable("get_similar_events", str(e))
    _store_source(r)
    q = news.tokens(situation)
    for h in hits:
        h["similarity"] = round(h["match"] + (0.25 if c and (h.get("country") or "") == c["iso2"] else 0), 2)
    hits.sort(key=lambda h: -h["similarity"])
    r.data = {"situation": situation, "terms": sorted(q), "precedents": hits[: max(1, limit)]}
    r.notes += [STORE_NOTE, "Similarity is keyword overlap, not semantic understanding; check each precedent.", UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="history", tier=2)
async def get_temporal_anomalies(country: Optional[str] = None, limit: int = 20) -> str:
    """Countries whose conflict-event reporting in the last 24 hours is unusually high or low compared with the
    same weekday and hours over the previous weeks (z-score), based on GDELT counts our collector records.

    Args:
        country: Optional country name or ISO code; omit to rank all tracked countries.
        limit: Maximum countries (default 20).
    """
    c = geo.country(country) if country else None
    r = Result("get_temporal_anomalies")
    candidates = [c] if c else geo.all_countries()
    now_bucket = int(time.time() // 3600)
    rows = []
    try:
        for cc in candidates:
            series = await history.count_series(cc["iso2"])
            if not series:
                continue
            last24 = sum(series.get(now_bucket - i, 0) for i in range(24))
            oldest = min(series)
            # Same 24h window 1..4 weeks earlier, only for weeks the collector was already running.
            have = [sum(series.get(now_bucket - 168 * w - i, 0) for i in range(24))
                    for w in range(1, 5) if now_bucket - 168 * w - 23 >= oldest]
            if len(have) < 2:
                rows.append({"country": cc["name"], "iso2": cc["iso2"], "last_24h": last24, "status": "insufficient_history"})
                continue
            mean = sum(have) / len(have)
            sd = (sum((w - mean) ** 2 for w in have) / len(have)) ** 0.5 or max(1.0, mean * 0.25)
            z = round((last24 - mean) / sd, 2)
            rows.append({"country": cc["name"], "iso2": cc["iso2"], "last_24h": last24, "baseline_mean": round(mean, 1),
                         "z_score": z, "status": "high" if z >= 2 else "low" if z <= -2 else "normal"})
    except history.HistoryUnavailable as e:
        return unavailable("get_temporal_anomalies", str(e))
    _store_source(r)
    rows.sort(key=lambda x: -abs(x.get("z_score") or 0))
    r.data = {"anomalies": rows[: max(1, limit)]}
    r.notes += [STORE_NOTE, "Needs at least two weeks of collection for a baseline."]
    return r.to_json()
