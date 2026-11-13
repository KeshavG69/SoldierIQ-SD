"""Country picture: risk index, brief bundle, coverage timeline, travel risk,
defense industrial base, and risk history."""

from __future__ import annotations

import asyncio
import math
from collections import Counter
from typing import Optional

from osint import geo, signals
from osint.core import UNTRUSTED_NOTE, Result, iso, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import news, world

RISK_NOTE = ("The risk index is our own transparent heuristic (0-100), not an official rating: "
             "35% US travel advisory level, 25% conflict events, 15% strike reports, 15% news pressure, "
             "10% internet disruption. Read the components, not just the number.")


def _scale(x: float, cap: float) -> float:
    return round(min(100.0, 100.0 * math.log1p(max(0.0, x)) / math.log1p(cap)), 1)


async def compute_risk(r: Result, c: dict, s: Optional[dict] = None) -> dict:
    if s is None:
        s = await signals.gather(r, gdelt_hours=24, strike_hours=24, news_hours=24, want=("gdelt", "strikes", "news"))
    adv_all, outages = await asyncio.gather(
        safe_fetch(r, "US State Department travel advisories", world.STATE_DEPT_URL, world.state_dept_advisories()),
        safe_fetch(r, "IODA internet outages", world.IODA_EVENTS_URL, world.ioda_outages(c["iso2"], 3)),
    )
    adv = (adv_all or {}).get(c["iso2"])
    level = (adv or {}).get("level")
    gd = [e for e in s["gdelt"] if geo.in_country(e["lon"], e["lat"], c)]
    st = [x for x in s["strikes"] if x["country"] == c["iso2"]]
    names = [c["name"], c["name_long"], c["admin"]]
    hl = signals.mentions(s["news"], names)
    outage_score = max((o["score"] for o in outages or []), default=0)
    comp = {
        "travel_advisory": {1: 5, 2: 25, 3: 55, 4: 85}.get(level, 30),
        "conflict_events": _scale(len(gd), 150),
        "strike_reports": _scale(sum(1 if x["verdict"] in ("corroborated", "official_source") else 0.4 for x in st), 20),
        "news_pressure": _scale(len(hl), 60),
        "internet_disruption": _scale(outage_score / 100, 100),
    }
    score = round(0.35 * comp["travel_advisory"] + 0.25 * comp["conflict_events"] + 0.15 * comp["strike_reports"]
                  + 0.15 * comp["news_pressure"] + 0.10 * comp["internet_disruption"], 1)
    band = "severe" if score >= 70 else "high" if score >= 50 else "elevated" if score >= 30 else "low"
    return {"country": geo.country_brief(c), "risk_index": score, "band": band, "components": comp,
            "inputs": {"us_advisory_level": level, "us_advisory_title": (adv or {}).get("title"),
                       "gdelt_conflict_events_24h": len(gd), "strike_reports_24h": len(st),
                       "headlines_24h": len(hl), "max_outage_score_3d": round(outage_score)},
            "_detail": {"advisory": adv, "gdelt": gd, "strikes": st, "headlines": hl, "outages": outages or []}}


@osint_tool(group="country", tier=1)
async def get_country_risk(country: str) -> str:
    """A country's current risk snapshot: a 0-100 index with its components (US travel advisory level,
    conflict events, strike reports, news pressure, internet disruption) and the raw inputs behind each.

    Args:
        country: Country name or ISO code.
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_country_risk", f"Unknown country {country!r}")
    r = Result("get_country_risk")
    risk = await compute_risk(r, c)
    risk.pop("_detail")
    r.data = risk
    r.notes.append(RISK_NOTE)
    return r.to_json()


@osint_tool(group="country", tier=1)
async def get_country_brief(country: str) -> str:
    """Everything needed to write a country intelligence brief, in one bundle: risk index and components, the
    US travel advisory text, top story clusters with corroboration, strike reports, the most-reported conflict
    locations, internet outages, and military aircraft over the country. Write the brief from this data and
    cite sources.

    Args:
        country: Country name or ISO code.
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_country_brief", f"Unknown country {country!r}")
    r = Result("get_country_brief")
    s = await signals.gather(r, gdelt_hours=24, strike_hours=48, news_hours=48, want=("gdelt", "strikes", "news", "aircraft"))
    gn = await safe_fetch(r, "Google News search", news.GN, news.google_news(c["name"], when="2d"))
    s["news"] = s["news"] + (gn or [])
    risk = await compute_risk(r, c, s)
    d = risk.pop("_detail")
    clusters = news.cluster_headlines(d["headlines"])
    places = Counter(e["place"].split(",")[0] for e in d["gdelt"] if e.get("place"))
    air = [a for a in s["aircraft"] if geo.in_country(a["lon"], a["lat"], c)]
    r.data = {"risk": risk, "advisory": d["advisory"], "top_stories": clusters[:12], "strike_reports": d["strikes"][:20],
              "most_reported_conflict_locations": [{"place": p, "events": n} for p, n in places.most_common(10)],
              "internet_outages": d["outages"][:5], "military_aircraft_overhead": len(air),
              "military_aircraft": air[:15]}
    r.notes += [RISK_NOTE, UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="country", tier=1)
async def get_country_coverage(country: str, days: int = 7) -> str:
    """A country's incident timeline: recent headlines about it grouped into incidents (similar headlines within
    the window), newest first, each with first/last report time and how many outlets reported it.

    Args:
        country: Country name or ISO code.
        days: Look-back window (1-7, default 7).
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_country_coverage", f"Unknown country {country!r}")
    days = max(1, min(int(days), 7))
    r = Result("get_country_coverage")
    gn = await safe_fetch(r, "Google News search", news.GN, news.google_news(c["name"], when=f"{days}d", ttl=1800))
    items, _ = await news.read_all_feeds()
    items = [i for i in news.published_after(items + (gn or []), days * 24)
             if any(n.lower() in i["title"].lower() for n in (c["name"], c["name_long"], c["admin"]))]
    clusters = news.cluster_headlines(items)
    clusters.sort(key=lambda x: x["last_seen"] or "", reverse=True)
    r.data = {"country": geo.country_brief(c), "days": days, "headlines": len(items), "incidents": clusters[:40]}
    r.notes.append(UNTRUSTED_NOTE)
    return r.to_json()


@osint_tool(group="country", tier=2)
async def prepare_travel_risk_assessment(countries: str) -> str:
    """Material for a travel or deployment risk assessment across 1-6 countries in travel order: for each, the US
    advisory level and summary, risk index and components, recent strike reports, internet disruption and active
    disease outbreaks. The analyst writes the assessment from this.

    Args:
        countries: Comma-separated country names or ISO codes in travel order, e.g. "AE, OM, YE".
    """
    names = [x.strip() for x in (countries or "").split(",") if x.strip()][:6]
    resolved = [geo.country(n) for n in names]
    if not names or any(x is None for x in resolved):
        bad = [n for n, x in zip(names, resolved) if x is None]
        return unavailable("prepare_travel_risk_assessment", f"Could not resolve: {', '.join(bad) or 'no countries given'}")
    r = Result("prepare_travel_risk_assessment")
    s = await signals.gather(r, gdelt_hours=24, strike_hours=48, news_hours=24, want=("gdelt", "strikes", "news"))
    outbreaks = await safe_fetch(r, "WHO Disease Outbreak News", world.WHO_DON_URL, world.who_outbreaks(40))
    legs = []
    for c in resolved:
        risk = await compute_risk(r, c, s)
        d = risk.pop("_detail")
        legs.append({"country": risk["country"], "risk_index": risk["risk_index"], "band": risk["band"],
                     "components": risk["components"], "advisory": d["advisory"], "strike_reports": d["strikes"][:8],
                     "internet_outages": d["outages"][:3],
                     "disease_outbreaks": [o for o in outbreaks or [] if c["name"].lower() in (o["title"] or "").lower()][:3]})
    r.data = {"itinerary": [c["name"] for c in resolved], "legs": legs,
              "highest_risk_leg": max(legs, key=lambda x: x["risk_index"])["country"]["name"]}
    r.notes += [RISK_NOTE, "This is input for an analyst, not a finished assessment or a security clearance."]
    return r.to_json()


DEFENSE_INDICATORS = {
    "military_expenditure_pct_gdp": "MS.MIL.XPND.GD.ZS",
    "military_expenditure_usd": "MS.MIL.XPND.CD",
    "military_expenditure_pct_government": "MS.MIL.XPND.ZS",
    "armed_forces_personnel": "MS.MIL.TOTL.P1",
    "armed_forces_pct_labor_force": "MS.MIL.TOTL.TF.ZS",
    "arms_imports_tiv": "MS.MIL.MPRT.KD",
    "arms_exports_tiv": "MS.MIL.XPRT.KD",
}


@osint_tool(group="country", tier=2)
async def get_defense_industrial_base(country: str) -> str:
    """A country's defense capacity indicators from the World Bank (sourced from SIPRI and IISS): military
    spending (USD, % of GDP, % of government spending), armed forces personnel, and arms imports and exports
    (SIPRI trend-indicator values), for the last ten years.

    Args:
        country: Country name or ISO code.
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_defense_industrial_base", f"Unknown country {country!r}")
    r = Result("get_defense_industrial_base")
    keys = list(DEFENSE_INDICATORS)
    vals = await asyncio.gather(*(safe_fetch(r, f"World Bank {DEFENSE_INDICATORS[k]}", world.WORLDBANK_URL,
                                             world.worldbank_indicator(c["iso3"], DEFENSE_INDICATORS[k])) for k in keys))
    r.data = {"country": geo.country_brief(c), "indicators": {k: v or [] for k, v in zip(keys, vals)}}
    r.notes.append("World Bank defense series come from SIPRI and IISS and lag by one to two years.")
    return r.to_json()


@osint_tool(group="country", tier=2)
async def get_country_history(country: str, days: int = 90) -> str:
    """A country's daily risk index history as recorded by our collector (one point per day), to see whether
    things are getting better or worse.

    Args:
        country: Country name or ISO code.
        days: How many days back (7-365, default 90).
    """
    from datetime import date, timedelta

    from osint import history

    c = geo.country(country)
    if not c:
        return unavailable("get_country_history", f"Unknown country {country!r}")
    r = Result("get_country_history")
    try:
        hist = await history.risk_history(c["iso2"])
        r.source("SoldierIQ risk history (Redis)", "", iso(), ok=True)
    except history.HistoryUnavailable as e:
        return unavailable("get_country_history", str(e))
    since = (date.today() - timedelta(days=max(7, min(int(days), 365)))).isoformat()
    points = [{"date": d, **v} for d, v in hist.items() if d >= since]
    trend = None
    if len(points) >= 7:
        last7 = sum(p["risk_index"] for p in points[-7:]) / 7
        prev = points[:-7][-7:]
        if prev:
            prev7 = sum(p["risk_index"] for p in prev) / len(prev)
            trend = "rising" if last7 - prev7 >= 5 else "falling" if prev7 - last7 >= 5 else "stable"
    r.data = {"country": geo.country_brief(c), "points": points, "trend_last_7d": trend}
    if not points:
        r.notes.append("No history yet: the collector records each country once a day after it starts running.")
    return r.to_json()
