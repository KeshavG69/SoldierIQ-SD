"""News intelligence: clustered headlines with source labels, claim checks,
keyword spikes, the source register, a world brief bundle, media perspective."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from app.settings import settings
from osint import geo
from osint.core import UNTRUSTED_NOTE, Result, get_json, safe_fetch, unavailable
from osint.registry import catalog, osint_tool
from osint.sources import gdelt, news, telegram

CORROBORATION_NOTE = ("'corroboration' describes coverage, not truth: 'corroborated' = 2+ distinct outlets including "
                      "a tier 1-2 outlet; 'single_publisher' = one outlet; 'state_media_only' = only tier-4 state media.")


def _outlet_profile(name: str) -> dict:
    o = news.OUTLET_BY_NAME.get(name)
    if not o:
        return {"name": name}
    return {k: o.get(k) for k in ("name", "tier", "country", "type", "state", "perspective") if o.get(k) is not None}


async def _headlines(r: Result, query: Optional[str], country: Optional[dict], hours: int) -> list[dict]:
    items, status = await news.read_all_feeds()
    ok = sum(1 for s in status if s["ok"])
    r.source("News RSS register", "", None, ok=ok > 0, error="" if ok else "no feed could be read")
    r.sources[-1]["feeds_read"] = f"{ok}/{len(status)}"
    terms = []
    if country:
        terms = [country["name"], country["name_long"], country["admin"]]
    if query:
        gn = await safe_fetch(r, "Google News search", news.GN, news.google_news(query, when=f"{max(1, hours // 24 or 1)}d"))
        items += gn or []
        terms.append(query)
    if country and not query:
        gn = await safe_fetch(r, "Google News search", news.GN, news.google_news(country["name"], when="1d"))
        items += gn or []
    items = news.published_after(items, hours)
    if terms:
        low = [t.lower() for t in terms if t]
        qtok = news.tokens(query) if query else set()
        items = [i for i in items if any(t in i["title"].lower() for t in low)
                 or (qtok and len(qtok & news.tokens(i["title"])) >= max(1, len(qtok) // 2))]
    seen, out = set(), []
    for i in items:
        k = (i["title"].lower()[:90], i["outlet"])
        if k not in seen:
            seen.add(k)
            out.append(i)
    return out


@osint_tool(group="news", tier=1)
async def get_news_intelligence(country: Optional[str] = None, query: Optional[str] = None, hours: int = 24,
                                limit: int = 20) -> str:
    """Current reporting as story clusters: each story with its lead headline, how many distinct outlets carry it,
    the best outlet tier, a corroboration state, and the outlets' profiles (tier, home country, state affiliation,
    perspective). Drawn from ~30 curated feeds (wires, broadcasters, defense press, think tanks, state media)
    plus Google News for a query.

    Args:
        country: Optional country name or ISO code to focus on.
        query: Optional free-text topic, e.g. "Strait of Hormuz mine", "Houthi Red Sea".
        hours: Look-back window (1-72, default 24).
        limit: Maximum story clusters (default 20).
    """
    c = geo.country(country) if country else None
    if country and not c:
        return unavailable("get_news_intelligence", f"Unknown country {country!r}")
    r = Result("get_news_intelligence")
    items = await _headlines(r, query, c, max(1, min(int(hours), 72)))
    clusters = news.cluster_headlines(items)
    for cl in clusters:
        cl["outlet_profiles"] = [_outlet_profile(o) for o in cl["outlets"][:6]]
    r.data = {"focus": {"country": c["name"] if c else None, "query": query, "hours": hours},
              "headline_count": len(items), "stories": clusters[: max(1, limit)]}
    r.notes += [CORROBORATION_NOTE, UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="news", tier=1)
async def get_news_clusters(topic: Optional[str] = None, hours: int = 12, min_outlets: int = 1, limit: int = 30) -> str:
    """Regroup the live headline stream into stories (headline similarity clustering) and rank them by how many
    distinct outlets report each, so widely reported developments stand out from single-outlet stories.

    Args:
        topic: Optional keyword filter applied to headlines before clustering.
        hours: Look-back window (1-48, default 12).
        min_outlets: Only return stories carried by at least this many outlets (default 1).
        limit: Maximum clusters (default 30).
    """
    r = Result("get_news_clusters")
    items = await _headlines(r, topic, None, max(1, min(int(hours), 48)))
    clusters = [c for c in news.cluster_headlines(items) if c["outlet_count"] >= max(1, min_outlets)]
    r.data = {"topic": topic, "hours": hours, "headline_count": len(items), "clusters": clusters[: max(1, limit)],
              "multi_outlet_stories": sum(1 for c in clusters if c["outlet_count"] >= 2)}
    r.notes += [CORROBORATION_NOTE, UNTRUSTED_NOTE]
    return r.to_json()


_NUM = re.compile(r"\b\d[\d,.]*\b")


@osint_tool(group="news", tier=1)
async def verify_claim(claim: str) -> str:
    """Check how a claim or headline is covered: searches Google News and GDELT for matching reports, counts the
    distinct publishers and their tiers, gives a coverage verdict (corroborated / single_publisher /
    state_media_only / low_tier_only / not_found), checks whether the claim's numbers appear in any matching
    headline, and lists fact-checks when available. Coverage is not proof of accuracy.

    Args:
        claim: The claim or headline to check, as one statement (max 300 characters).
    """
    claim = (claim or "").strip()[:300]
    if len(claim) < 8:
        return unavailable("verify_claim", "Claim is too short to check")
    r = Result("verify_claim")
    qtok = sorted(news.tokens(claim), key=len, reverse=True)[:7]
    query = " ".join(qtok)
    gn_task = safe_fetch(r, "Google News search", news.GN, news.google_news(query, when="7d"))
    gd_task = safe_fetch(r, "GDELT DOC 2.0", gdelt.DOC_URL, gdelt.doc_search(" ".join(qtok[:5]), timespan="7d", max_records=75))
    gn, gd = await asyncio.gather(gn_task, gd_task)
    matches = []
    for it in gn or []:
        overlap = len(set(qtok) & news.tokens(it["title"])) / (len(qtok) or 1)
        if overlap >= 0.45:
            matches.append({"title": it["title"], "outlet": it["outlet"], "tier": it.get("tier"), "url": it["url"],
                            "published": it.get("published"), "overlap": round(overlap, 2)})
    for a in (gd or {}).get("articles") or []:
        overlap = len(set(qtok) & news.tokens(a.get("title") or "")) / (len(qtok) or 1)
        if overlap >= 0.45:
            name, tier = news.domain_tier(a.get("domain") or a.get("url") or "")
            matches.append({"title": news.clean(a.get("title"), 300), "outlet": name or a.get("domain"), "tier": tier,
                            "url": a.get("url"), "published": a.get("seendate"), "overlap": round(overlap, 2)})
    publishers: dict[str, Optional[int]] = {}
    for m in matches:
        publishers.setdefault(m["outlet"], m["tier"])
    tiers = [t for t in publishers.values() if t]
    if not matches:
        verdict = "not_found"
    elif len(publishers) >= 2 and any(t <= 2 for t in tiers):
        verdict = "corroborated"
    elif tiers and min(tiers) >= 4:
        verdict = "state_media_only"
    elif len(publishers) == 1:
        verdict = "single_publisher"
    else:
        verdict = "low_tier_only"
    claim_numbers = {n.strip(".,") for n in _NUM.findall(claim)}
    seen_numbers = {n.strip(".,") for m in matches for n in _NUM.findall(m["title"])}
    fact_checks = []
    if settings.GOOGLE_FACTCHECK_API_KEY:
        fc = await safe_fetch(r, "Google Fact Check Tools", "https://factchecktools.googleapis.com", _factcheck(claim))
        fact_checks = fc or []
    times = sorted(m["published"] for m in matches if m.get("published"))
    r.data = {
        "claim": claim, "search_terms": query, "verdict": verdict, "distinct_publishers": len(publishers),
        "publishers": [{"outlet": k, "tier": v} for k, v in sorted(publishers.items(), key=lambda x: (x[1] or 9))][:25],
        "figures_not_found_in_matches": sorted(claim_numbers - seen_numbers),
        "first_seen": times[0] if times else None, "last_seen": times[-1] if times else None,
        "matching_reports": sorted(matches, key=lambda m: (m["tier"] or 9, -m["overlap"]))[:15],
        "fact_checks": fact_checks,
    }
    r.notes += ["'not_found' means no matching coverage was found in 7 days, not that the claim is false.",
                "Figures listed under figures_not_found_in_matches were not stated by any matching headline.",
                UNTRUSTED_NOTE]
    return r.to_json()


async def _factcheck(claim: str):
    data = await get_json("https://factchecktools.googleapis.com/v1alpha1/claims:search",
                          params={"query": claim, "key": settings.GOOGLE_FACTCHECK_API_KEY, "pageSize": 5})
    out = []
    for cl in data.get("claims") or []:
        for rev in cl.get("claimReview") or []:
            out.append({"claim": cl.get("text"), "rating": rev.get("textualRating"),
                        "publisher": (rev.get("publisher") or {}).get("name"), "date": rev.get("reviewDate"),
                        "url": rev.get("url")})
    return out, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@osint_tool(group="news", tier=1)
async def get_keyword_spikes(keyword: Optional[str] = None, days: int = 7) -> str:
    """Detect unusual surges in coverage. With a keyword: GDELT's worldwide article volume for it over `days`,
    comparing the last 24 hours with the earlier daily average. Without a keyword: the words rising fastest in
    our headline stream (last 6 hours vs the 24 hours before), with sample headlines.

    Args:
        keyword: Optional term or phrase, e.g. "Hormuz", "drone", "CVE-2026-1234". Omit for automatic spikes.
        days: Baseline window for the keyword mode (2-30, default 7).
    """
    r = Result("get_keyword_spikes")
    if keyword:
        days = max(2, min(int(days), 30))
        q = f'"{keyword}"' if " " in keyword.strip() else keyword.strip()
        data = await safe_fetch(r, "GDELT DOC 2.0 timeline", gdelt.DOC_URL,
                                gdelt.doc_search(q, mode="timelinevolraw", timespan=f"{days}d"))
        series = []
        for tl in (data or {}).get("timeline") or []:
            series = [{"date": p.get("date"), "count": p.get("value")} for p in tl.get("data") or []]
            break
        if not series:
            r.data = {"keyword": keyword, "series": []}
            return r.to_json()
        # Bucket into days.
        per_day: dict[str, int] = {}
        for p in series:
            d = (p["date"] or "")[:8]
            per_day[d] = per_day.get(d, 0) + int(p["count"] or 0)
        daysorted = sorted(per_day.items())
        last = daysorted[-1][1] if daysorted else 0
        prior = [v for _, v in daysorted[:-1]] or [0]
        avg = sum(prior) / len(prior)
        ratio = round(last / avg, 2) if avg else None
        r.data = {"keyword": keyword, "articles_last_day": last, "daily_average_before": round(avg, 1),
                  "ratio": ratio, "spike": bool(ratio and ratio >= 2 and last >= 20),
                  "daily": [{"day": d, "articles": v} for d, v in daysorted]}
        r.notes.append("Counts are GDELT-monitored articles worldwide; the latest day may be partial.")
        return r.to_json()
    items, status = await news.read_all_feeds()
    ok = sum(1 for s in status if s["ok"])
    r.source("News RSS register", "", None, ok=ok > 0)
    now = datetime.now(timezone.utc)
    recent, before = Counter(), Counter()
    samples: dict[str, list[str]] = {}
    for it in items:
        try:
            t = datetime.fromisoformat((it.get("published") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        age = (now - t).total_seconds() / 3600
        toks = news.tokens(it["title"])
        if age <= 6:
            recent.update(toks)
            for w in toks:
                samples.setdefault(w, []).append(it["title"])
        elif age <= 30:
            before.update(toks)
    spikes = []
    for w, n in recent.items():
        base = before.get(w, 0) / 4  # 24h before -> per-6h average
        if n >= 4 and n >= 3 * max(base, 0.5):
            spikes.append({"term": w, "last_6h": n, "prior_6h_average": round(base, 1),
                           "ratio": round(n / max(base, 0.5), 1), "sample_headlines": samples[w][:3]})
    spikes.sort(key=lambda x: (-x["ratio"], -x["last_6h"]))
    r.data = {"mode": "automatic", "spikes": spikes[:25]}
    r.notes.append(UNTRUSTED_NOTE)
    return r.to_json()


@osint_tool(group="news", tier=1)
async def get_sources() -> str:
    """The OSINT source register: every news outlet and Telegram channel the tools read, with our tier,
    home country, state affiliation and perspective labels, plus every data source and whether it is configured.
    Use it to explain where an answer came from and how far to trust it."""
    r = Result("get_sources")
    r.source("SoldierIQ OSINT register", "", None, ok=True)
    r.data = {
        "tier_legend": {"1": "wire service, newspaper of record or official body", "2": "established outlet or specialist",
                        "3": "partisan, state-aligned or single-perspective outlet",
                        "4": "state media of a belligerent / propaganda risk"},
        "news_outlets": [{k: v for k, v in o.items() if k != "url"} for o in news.OUTLETS],
        "telegram_channels": [{"handle": h, "class": c, "note": n} for h, (c, _, n) in telegram.CHANNELS.items()],
        "tools": catalog(),
        "data_sources": DATA_SOURCES,
    }
    return r.to_json(max_chars=60_000)


DATA_SOURCES = [
    {"name": "adsb.lol", "use": "military aircraft (ADS-B)", "terms": "ODbL open data", "key": None},
    {"name": "aisstream.io", "use": "live ship positions (AIS)", "terms": "free API key", "key": "AISSTREAM_API_KEY"},
    {"name": "IMF PortWatch", "use": "chokepoint transits", "terms": "open data, attribution", "key": None},
    {"name": "GDELT 2.0", "use": "news-coded events, article search", "terms": "open, attribution", "key": None},
    {"name": "Telegram (t.me/s web preview)", "use": "strike reports", "terms": "public posts", "key": None},
    {"name": "ACLED", "use": "curated conflict events", "terms": "account; commercial use needs a licence", "key": "ACLED_USERNAME"},
    {"name": "UCDP GED", "use": "curated conflict events", "terms": "API token, CC BY 4.0", "key": "UCDP_API_TOKEN"},
    {"name": "USGS", "use": "earthquakes", "terms": "public domain", "key": None},
    {"name": "GDACS", "use": "disaster alerts", "terms": "EC JRC, attribution", "key": None},
    {"name": "NASA EONET", "use": "natural events", "terms": "public", "key": None},
    {"name": "NASA FIRMS", "use": "thermal anomalies", "terms": "free MAP_KEY", "key": "FIRMS_MAP_KEY"},
    {"name": "Safecast", "use": "radiation readings", "terms": "CC0", "key": None},
    {"name": "IODA (Georgia Tech)", "use": "internet outages", "terms": "research use, attribution", "key": None},
    {"name": "TeleGeography Submarine Cable Map", "use": "cable landings", "terms": "CC BY-SA", "key": None},
    {"name": "CISA KEV", "use": "exploited vulnerabilities", "terms": "public domain", "key": None},
    {"name": "abuse.ch Feodo Tracker", "use": "botnet C2 servers", "terms": "CC0", "key": None},
    {"name": "abuse.ch URLhaus / ThreatFox", "use": "malware URLs, IOCs", "terms": "free Auth-Key", "key": "ABUSECH_AUTH_KEY"},
    {"name": "ransomware.live", "use": "ransomware victims", "terms": "public API", "key": None},
    {"name": "OFAC SDN", "use": "US sanctions", "terms": "public domain", "key": None},
    {"name": "UN Security Council Consolidated List", "use": "UN sanctions", "terms": "public", "key": None},
    {"name": "US State Department", "use": "travel advisories", "terms": "public domain", "key": None},
    {"name": "UNHCR Refugee Data", "use": "displacement", "terms": "CC BY 4.0", "key": None},
    {"name": "WHO Disease Outbreak News", "use": "outbreaks", "terms": "public", "key": None},
    {"name": "World Bank WDI", "use": "defense indicators", "terms": "CC BY 4.0", "key": None},
    {"name": "Natural Earth", "use": "country shapes, cities", "terms": "public domain", "key": None},
    {"name": "Google News RSS", "use": "headline search", "terms": "public RSS", "key": None},
    {"name": "Bluesky", "use": "social posts", "terms": "public API", "key": None},
    {"name": "Reddit", "use": "social velocity", "terms": "official OAuth API, free app credentials", "key": "REDDIT_CLIENT_ID"},
    {"name": "Polymarket", "use": "prediction markets", "terms": "public API; geo-restricted in some countries", "key": None},
    {"name": "Windy Webcams", "use": "webcams", "terms": "free API key, attribution", "key": "WINDY_API_KEY"},
    {"name": "US EIA", "use": "energy prices and stocks", "terms": "free API key", "key": "EIA_API_KEY"},
    {"name": "FAA NAS Status", "use": "US airport status", "terms": "public", "key": None},
    {"name": "Copernicus Sentinel-5P", "use": "NO2 columns", "terms": "free account", "key": "COPERNICUS_CLIENT_ID"},
]


@osint_tool(group="news", tier=2)
async def get_world_brief(limit: int = 12) -> str:
    """The material for a world situation brief: the most widely reported stories of the last 12 hours (with
    corroboration), confirmed strike reports, and theaters at elevated air posture. Write the brief from this data
    and cite the outlets.

    Args:
        limit: Maximum stories (default 12).
    """
    from osint import signals
    from osint.tools.military import _posture

    r = Result("get_world_brief")
    items = await signals.headlines(r, hours=12)
    s = await signals.gather(r, want=("strikes", "aircraft"), strike_hours=12)
    clusters = news.cluster_headlines(items)
    top = sorted(clusters, key=lambda c: (-c["outlet_count"], c["best_tier"] or 9))[: max(1, limit)]
    hot = [p for p in (_posture(t, geo.THEATERS[t], s["aircraft"]) for t in geo.THEATERS) if p["posture"] != "normal"]
    r.data = {"top_stories": top,
              "confirmed_strike_reports": [x for x in s["strikes"] if x["verdict"] in ("corroborated", "official_source")][:12],
              "elevated_air_posture": hot}
    r.notes += [CORROBORATION_NOTE, UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="news", tier=2)
async def get_media_perspective(country: str, hours: int = 48) -> str:
    """How different media ecosystems cover one country: headlines about it grouped by outlet type and
    allegiance (international wires and broadcasters, regional outlets, state media of interested powers),
    to compare framing and spot narratives pushed by one side.

    Args:
        country: Country name or ISO code.
        hours: Look-back window (6-96, default 48).
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_media_perspective", f"Unknown country {country!r}")
    r = Result("get_media_perspective")
    items = await _headlines(r, None, c, max(6, min(int(hours), 96)))
    groups: dict[str, list] = {}
    for it in items:
        prof = news.OUTLET_BY_NAME.get(it["feed"]) if it["feed"] != "Google News" else None
        tier = it.get("tier") or (prof or {}).get("tier")
        if prof and prof.get("state"):
            key = f"state-affiliated ({prof['state']})"
        elif tier == 4:
            key = "state media"
        elif tier == 1:
            key = "international wires / newspapers of record"
        elif prof and prof.get("perspective"):
            key = f"perspective: {prof['perspective']}"
        elif tier in (2, 3):
            key = "established and specialist outlets"
        else:
            key = "other / unrated outlets"
        groups.setdefault(key, []).append({"title": it["title"], "outlet": it["outlet"], "published": it.get("published"),
                                           "url": it["url"]})
    r.data = {"country": geo.country_brief(c), "hours": hours,
              "groups": {k: v[:12] for k, v in sorted(groups.items(), key=lambda x: -len(x[1]))},
              "counts": {k: len(v) for k, v in groups.items()}}
    r.notes += ["Groupings use our outlet register; unrated outlets came via Google News.", UNTRUSTED_NOTE]
    return r.to_json()
