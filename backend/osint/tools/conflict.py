"""Conflict and escalation: events, strike reports, hotspots, convergence,
focal points, and the cross-domain alert digest."""

from __future__ import annotations

import asyncio
import math
from collections import Counter, defaultdict
from typing import Optional

from app.settings import settings
from osint import geo, signals
from osint.core import UNTRUSTED_NOTE, Result, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import conflict as conflict_src
from osint.sources import hazards, security, world

GDELT_NOTE = ("GDELT events are machine-coded from news reports: they show what is being reported "
              "where, not verified incidents. Use num_sources as a rough confidence signal.")
STRIKE_NOTE = ("Strike reports are parsed from public Telegram channels by keyword rules. Reports from "
               "partisan or state-media channels count only when another independent group reports the same "
               "place within 2 hours (verdict 'corroborated'). Treat 'single_source' and "
               "'uncorroborated_partisan' as unconfirmed.")


@osint_tool(group="conflict", tier=1)
async def get_conflict_events(region: Optional[str] = None, hours: int = 24, include_unverified_news_events: bool = True) -> str:
    """Recent armed-conflict events in a region: strike/intercept/claim reports from public Telegram channels
    with a corroboration verdict, GDELT news-coded clashes and assaults, and (when configured) curated
    ACLED and UCDP events with fatalities.

    Args:
        region: A country (name or ISO code), theater id (iran, levant, red-sea, black-sea...), or
            "west,south,east,north" box. Omit for worldwide.
        hours: Look-back window in hours for the live layers (1-72, default 24).
        include_unverified_news_events: Include GDELT machine-coded events (default true).
    """
    hours = max(1, min(int(hours), 72))
    bbox, label = geo.region_bbox(region)
    if region and not bbox:
        return unavailable("get_conflict_events", f"Could not resolve region {region!r}")
    c = geo.country(region) if region else None
    r = Result("get_conflict_events")

    def keep(e):
        if e.get("lat") is None:
            return False
        if c:
            return geo.in_country(e["lon"], e["lat"], c) or (e.get("country") or "").upper() == c["iso2"]
        return bbox is None or geo.in_bbox(e["lon"], e["lat"], bbox)

    tasks = [signals.strikes(r, hours)]
    if include_unverified_news_events:
        tasks.append(signals.conflict_gdelt(r, min(hours, 12)))
    results = await asyncio.gather(*tasks)
    strike_list = [s for s in results[0] if keep(s)]
    gd = [e for e in (results[1] if len(results) > 1 else []) if keep(e)]
    gd.sort(key=lambda e: (e["num_sources"], e["date_added"]), reverse=True)

    curated: dict = {}
    if settings.ACLED_USERNAME and settings.ACLED_PASSWORD:
        acled = await safe_fetch(r, "ACLED", conflict_src.ACLED_READ_URL,
                                 conflict_src.acled_events(c["name"] if c else None, days=max(7, hours // 24 + 7)))
        if acled:
            curated["acled"] = [e for e in acled if keep(e)][:60]
    if settings.UCDP_API_TOKEN:
        ucdp = await safe_fetch(r, "UCDP GED", conflict_src.UCDP_URL, conflict_src.ucdp_events(c["name"] if c else None, days=120))
        if ucdp:
            curated["ucdp"] = [e for e in ucdp if keep(e)][:60]
    if not curated:
        r.notes.append("Curated datasets (ACLED, UCDP) are not configured; only live, unverified layers are shown.")

    verdicts = Counter(s["verdict"] for s in strike_list)
    r.data = {
        "region": label, "hours": hours,
        "strike_reports": {"count": len(strike_list), "by_verdict": dict(verdicts), "events": strike_list[:60]},
        "gdelt_events": {"count": len(gd), "by_category": dict(Counter(e["category"] for e in gd)), "events": gd[:50]},
        **({"curated": curated} if curated else {}),
    }
    r.notes += [STRIKE_NOTE, GDELT_NOTE, UNTRUSTED_NOTE]
    return r.to_json()


def _norm(x: float, cap: float) -> float:
    return round(min(100.0, 100.0 * math.log1p(x) / math.log1p(cap)), 1) if x > 0 else 0.0


@osint_tool(group="conflict", tier=1)
async def get_hotspot_escalation(hotspot: Optional[str] = None, limit: int = 30) -> str:
    """Escalation scores (1-5) for curated hotspots such as the Strait of Hormuz, southern Lebanon, Gaza,
    the Red Sea, eastern Ukraine and the Taiwan Strait. Each score blends a fixed baseline with four live
    components: news pressure, strike reports, conflict events and military air activity nearby.

    Args:
        hotspot: Optional hotspot id (e.g. strait_of_hormuz, south_lebanon, bab_el_mandeb, taiwan_strait). Omit for all.
        limit: Maximum hotspots returned, highest first.
    """
    ids = [hotspot] if hotspot else list(geo.HOTSPOTS)
    if any(i not in geo.HOTSPOTS for i in ids):
        return unavailable("get_hotspot_escalation", f"Unknown hotspot. Known: {', '.join(geo.HOTSPOTS)}")
    r = Result("get_hotspot_escalation")
    s = await signals.gather(r, gdelt_hours=6, strike_hours=24, news_hours=24, want=("gdelt", "strikes", "aircraft", "news"))
    rows = []
    for hid in ids:
        h = geo.HOTSPOTS[hid]
        names = [h["name"].split("(")[0].split("/")[0].strip()] + [geo.country(cc)["name"] for cc in h["countries"] if geo.country(cc)]
        news_n = len(signals.mentions(s["news"], names))
        strike_n = sum({"corroborated": 1.0, "official_source": 1.0, "single_source": 0.5, "uncorroborated_partisan": 0.25}[x["verdict"]]
                       for x in signals.within(s["strikes"], h["lat"], h["lon"], h["radius_km"]))
        gd_n = len(signals.within(s["gdelt"], h["lat"], h["lon"], h["radius_km"]))
        air_n = len(signals.within(s["aircraft"], h["lat"], h["lon"], h["radius_km"] * 1.5))
        comp = {"news_pressure": _norm(news_n, 40), "strike_reports": _norm(strike_n, 15),
                "conflict_events": _norm(gd_n, 60), "military_air": _norm(air_n, 15)}
        dynamic = 0.30 * comp["news_pressure"] + 0.30 * comp["strike_reports"] + 0.25 * comp["conflict_events"] + 0.15 * comp["military_air"]
        score = round(0.4 * h["baseline"] + 0.6 * (1 + dynamic / 25), 2)
        rows.append({"hotspot": hid, "name": h["name"], "score": min(5.0, score), "baseline": h["baseline"],
                     "trend_hint": "above_baseline" if score > h["baseline"] + 0.4 else "below_baseline" if score < h["baseline"] - 0.4 else "at_baseline",
                     "components": comp, "counts": {"headlines": news_n, "strike_reports_weighted": strike_n,
                                                    "gdelt_events": gd_n, "military_aircraft": air_n}})
    rows.sort(key=lambda x: -x["score"])
    r.data = {"hotspots": rows[: max(1, limit)]}
    r.notes += ["Scores are our own heuristic (40% fixed baseline, 60% live signals in the last 24h); "
                "use the counts to judge them.", GDELT_NOTE]
    return r.to_json()


@osint_tool(group="conflict", tier=1)
async def get_signal_convergence(region: Optional[str] = None, cell_degrees: float = 2.0, min_signal_types: int = 2) -> str:
    """Places where several independent signal types fire at once: grid cells containing two or more of
    strike reports, GDELT conflict events, military aircraft, earthquakes, and (when configured) satellite
    thermal anomalies. Convergence is a prompt to look closer, not proof of an event.

    Args:
        region: Optional country, theater id or "west,south,east,north" box. Omit for worldwide.
        cell_degrees: Grid cell size in degrees (0.5-5, default 2).
        min_signal_types: Minimum distinct signal types in a cell (default 2).
    """
    cell = max(0.5, min(float(cell_degrees), 5.0))
    bbox, label = geo.region_bbox(region)
    r = Result("get_signal_convergence")
    s = await signals.gather(r, gdelt_hours=6, strike_hours=24, want=("gdelt", "strikes", "aircraft", "quakes"))
    layers = {"strike_reports": s["strikes"], "gdelt_conflict": s["gdelt"], "military_aircraft": s["aircraft"],
              "earthquakes": [q for q in s["quakes"] if (q.get("magnitude") or 0) >= 4.5]}
    if bbox and settings.FIRMS_MAP_KEY:
        layers["thermal_anomalies"] = await safe_fetch(r, "NASA FIRMS VIIRS", "https://firms.modaps.eosdis.nasa.gov",
                                                       hazards.firms_hotspots(bbox, 1)) or []
    cells: dict[tuple, dict] = defaultdict(lambda: defaultdict(int))
    for name, items in layers.items():
        for it in items:
            if it.get("lat") is None or (bbox and not geo.in_bbox(it["lon"], it["lat"], bbox)):
                continue
            key = (math.floor(it["lat"] / cell) * cell, math.floor(it["lon"] / cell) * cell)
            cells[key][name] += 1
    out = []
    for (lat0, lon0), counts in cells.items():
        if len(counts) >= max(2, min_signal_types):
            clat, clon = lat0 + cell / 2, lon0 + cell / 2
            ctry = geo.country_at(clon, clat)
            out.append({"cell_center": [round(clat, 2), round(clon, 2)], "cell_degrees": cell,
                        "country": ctry["name"] if ctry else None, "signal_types": len(counts), "counts": dict(counts)})
    out.sort(key=lambda x: (-x["signal_types"], -sum(x["counts"].values())))
    r.data = {"region": label, "convergence_cells": out[:40]}
    r.notes += ["Military aircraft on ADS-B cluster around air bases and tanker tracks; weigh them lightly.", GDELT_NOTE]
    return r.to_json()


@osint_tool(group="conflict", tier=1)
async def get_focal_points(region: Optional[str] = None, limit: int = 20) -> str:
    """The actors, places and countries drawing the most attention right now, ranked by how many separate
    signal streams mention them (GDELT event actors and places, strike-report places, news headlines).

    Args:
        region: Optional country, theater id or box to restrict geolocated signals. Omit for worldwide.
        limit: Maximum focal points returned (default 20).
    """
    bbox, label = geo.region_bbox(region)
    r = Result("get_focal_points")
    s = await signals.gather(r, gdelt_hours=6, strike_hours=24, news_hours=24, want=("gdelt", "strikes", "news"))
    generic = {"police", "military", "government", "president", "prime minister", "minister", "court", "people",
               "school", "student", "students", "company", "business", "media", "citizen", "protester", "protesters",
               "united states", "security forces", "army", "official", "officials", "attorney", "judge", "prison",
               "lawmaker", "senate", "congress", "parliament", "hospital", "doctor", "children", "women", "man", "men"}
    score: dict[str, dict] = defaultdict(lambda: {"gdelt": 0, "strikes": 0, "headlines": 0})
    for e in s["gdelt"]:
        if bbox and not geo.in_bbox(e["lon"], e["lat"], bbox):
            continue
        for a in (e.get("actor1"), e.get("actor2")):
            if a and a.lower() not in generic:
                score[a.title()]["gdelt"] += 1
        if e.get("place"):
            score[e["place"].split(",")[0].strip()]["gdelt"] += 1
    for st in s["strikes"]:
        if bbox and not geo.in_bbox(st["lon"], st["lat"], bbox):
            continue
        score[st["place"]]["strikes"] += 1
    names = list(score.keys()) + [c["name"] for c in geo.all_countries()]
    for h in s["news"]:
        title = h.get("title") or ""
        for n in set(names):
            if len(n) > 3 and n.lower() in title.lower():
                score[n]["headlines"] += 1
    rows = []
    for name, cnt in score.items():
        streams = sum(1 for v in cnt.values() if v)
        if streams >= 2:
            rows.append({"focal_point": name, "streams": streams, **cnt, "total": sum(cnt.values())})
    rows.sort(key=lambda x: (-x["streams"], -x["total"]))
    r.data = {"region": label, "focal_points": rows[: max(1, limit)]}
    r.notes.append("A focal point needs at least two different signal streams; counts are mentions, not incidents.")
    return r.to_json()


@osint_tool(group="conflict", tier=1)
async def get_alert_digest() -> str:
    """Everything that crossed a threshold in the last 24 hours, in one rollup: theaters at elevated or
    critical air posture, corroborated strike reports, major internet outages, red/orange disaster alerts,
    strong earthquakes, and newly added actively exploited vulnerabilities. Quiet domains are listed as
    quiet; failed domains as unavailable, so silence is never mistaken for calm."""
    from osint.tools.military import _posture

    r = Result("get_alert_digest")
    s = await signals.gather(r, strike_hours=24, want=("strikes", "aircraft", "quakes"))
    outages, gd_alerts, kev = await asyncio.gather(
        safe_fetch(r, "IODA internet outages", world.IODA_EVENTS_URL, world.ioda_outages(None, 1)),
        safe_fetch(r, "GDACS disaster alerts", hazards.GDACS_URL, hazards.gdacs_events()),
        safe_fetch(r, "CISA KEV", security.CISA_KEV_URL, security.cisa_kev()),
    )
    from datetime import date, timedelta

    def source_ok(prefix: str) -> bool:
        return any(src["ok"] for src in r.sources if src["name"].startswith(prefix))

    domains: dict[str, dict] = {}
    if not source_ok("adsb.lol"):
        domains["military_air"] = {"status": "unavailable"}
    else:
        hot = [p for p in (_posture(t, geo.THEATERS[t], s["aircraft"]) for t in geo.THEATERS) if p["posture"] != "normal"]
        domains["military_air"] = {"status": "alert" if hot else "quiet", "items": hot,
                                   "caveat": "Quiet only covers airspace open ADS-B can see; see get_military_posture coverage."}
    if not source_ok("Telegram"):
        domains["strikes"] = {"status": "unavailable"}
    else:
        conf = [x for x in s["strikes"] if x["verdict"] in ("corroborated", "official_source")]
        domains["strikes"] = {"status": "alert" if conf else "quiet", "items": conf[:20]}
    if outages is None:
        domains["internet_outages"] = {"status": "unavailable"}
    else:
        big = [o for o in outages if o["score"] >= 1000][:15]
        domains["internet_outages"] = {"status": "alert" if big else "quiet", "items": big}
    if gd_alerts is None:
        domains["disasters"] = {"status": "unavailable"}
    else:
        red = [g for g in gd_alerts if (g.get("alert_level") or "").lower() == "red"]
        domains["disasters"] = {"status": "alert" if red else "quiet", "items": red[:15],
                                "orange_count": sum(1 for g in gd_alerts if (g.get("alert_level") or "").lower() == "orange")}
    if not source_ok("USGS"):
        domains["earthquakes"] = {"status": "unavailable"}
    else:
        big_q = [q for q in s["quakes"] if (q.get("magnitude") or 0) >= 6.5]
        domains["earthquakes"] = {"status": "alert" if big_q else "quiet", "items": big_q[:10]}
    if kev is None:
        domains["exploited_vulnerabilities"] = {"status": "unavailable"}
    else:
        since = (date.today() - timedelta(days=2)).isoformat()
        new = [k for k in kev if (k.get("date_added") or "") >= since]
        domains["exploited_vulnerabilities"] = {"status": "alert" if new else "quiet", "items": new[:15]}
    r.data = {"domains": domains,
              "alerting": [k for k, v in domains.items() if v["status"] == "alert"],
              "unavailable": [k for k, v in domains.items() if v["status"] == "unavailable"]}
    r.notes += [STRIKE_NOTE, "Internet outage scores come from IODA; >=1000 is a large anomaly."]
    return r.to_json()
