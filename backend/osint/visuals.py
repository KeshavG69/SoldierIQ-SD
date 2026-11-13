"""Build interactive map payloads from OSINT sources.

The server, not the model, turns OSINT results into map features, so the
coordinates are exact and the agent's reply stays small. The frontend draws
each feature as a tappable icon; `details` is what the tap reveals.

Feature:
  {id, layer, lat, lon, title, time, severity, verdict?, heading?, source, url?, text?, details{}}
severity: critical | high | elevated | moderate | low | info
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from app.settings import settings
from osint import geo, signals
from osint.core import Result, safe_fetch
from osint.sources import hazards, world

LAYERS: dict[str, dict] = {
    "strikes": {"label": "Strike reports", "icon": "strike", "needs": None},
    "aircraft": {"label": "Military aircraft", "icon": "aircraft", "needs": None},
    "conflict": {"label": "Reported clashes (GDELT)", "icon": "conflict", "needs": None},
    "chokepoints": {"label": "Chokepoints", "icon": "chokepoint", "needs": None},
    "hotspots": {"label": "Hotspots", "icon": "hotspot", "needs": None},
    "quakes": {"label": "Earthquakes", "icon": "quake", "needs": None},
    "disasters": {"label": "Disaster alerts", "icon": "hazard", "needs": None},
    "outages": {"label": "Internet outages", "icon": "outage", "needs": None},
    "fires": {"label": "Thermal anomalies", "icon": "fire", "needs": "FIRMS_MAP_KEY"},
    "ships": {"label": "Ships (AIS)", "icon": "ship", "needs": "AISSTREAM_API_KEY"},
}
DEFAULT_LAYERS = ("strikes", "aircraft", "conflict", "chokepoints", "hotspots")
MAX_FEATURES = 350
VERDICT_SEVERITY = {"official_source": "high", "corroborated": "high", "single_source": "elevated",
                    "uncorroborated_partisan": "moderate"}


MAP_TTL_S = 30 * 86400


async def store_map(payload: dict, owner: Optional[str]) -> str:
    """Keep the full map server-side (30 days); the model only sees a summary and the id."""
    import uuid

    from osint.core import cache_set

    map_id = uuid.uuid4().hex
    await cache_set(f"map:{map_id}", {"owner": owner, "payload": payload}, MAP_TTL_S)
    return map_id


async def load_map(map_id: str, owner: Optional[str]) -> Optional[dict]:
    from osint.core import cache_get

    if not map_id.isalnum() or len(map_id) != 32:
        return None
    hit = await cache_get(f"map:{map_id}")
    if not hit or (hit.get("owner") and owner and hit["owner"] != owner):
        return None
    return hit["payload"]


def available_layers() -> list[str]:
    return [k for k, v in LAYERS.items() if not v["needs"] or getattr(settings, v["needs"], "")]


def _in(bbox, lat, lon) -> bool:
    return bbox is None or (lat is not None and lon is not None and geo.in_bbox(lon, lat, bbox))


async def build_map(region: Optional[str], layers: Optional[list[str]], hours: int = 24, title: Optional[str] = None) -> dict:
    hours = max(1, min(int(hours), 72))
    bbox, label = geo.region_bbox(region)
    wanted = [x for x in (layers or DEFAULT_LAYERS) if x in LAYERS]
    usable = set(available_layers())
    skipped = [x for x in wanted if x not in usable]
    wanted = [x for x in wanted if x in usable]
    r = Result("show_map")
    feats: dict[str, list[dict]] = {k: [] for k in wanted}
    s = await signals.gather(
        r, gdelt_hours=min(hours, 12), strike_hours=hours,
        want=tuple(x for x, need in (("strikes", "strikes"), ("aircraft", "aircraft"), ("gdelt", "conflict"),
                                    ("quakes", "quakes")) if need in wanted))

    if "strikes" in wanted:
        for i, x in enumerate(s.get("strikes") or []):
            if _in(bbox, x["lat"], x["lon"]):
                feats["strikes"].append({
                    "id": f"strike-{i}", "layer": "strikes", "lat": x["lat"], "lon": x["lon"],
                    "title": f"{x['kind'].title()} reported: {x['place']}", "time": x["time"],
                    "severity": x["severity"] if x["verdict"] in ("corroborated", "official_source") else VERDICT_SEVERITY[x["verdict"]],
                    "verdict": x["verdict"], "source": f"t.me/{x['channel']} ({x['channel_class']})", "url": x["url"],
                    "text": x["text"][:400],
                    "details": {"Kind": x["kind"], "Severity (keyword)": x["severity"], "Verdict": x["verdict"].replace("_", " "),
                                "Other groups reporting": x["corroborating_groups"], "Channel": x["channel_note"]}})
    if "aircraft" in wanted:
        for a in s.get("aircraft") or []:
            if _in(bbox, a["lat"], a["lon"]):
                feats["aircraft"].append({
                    "id": f"ac-{a['hex']}", "layer": "aircraft", "lat": a["lat"], "lon": a["lon"],
                    "title": f"{a['callsign'] or a['registration'] or a['hex']} · {a['type'] or 'unknown type'}",
                    "time": None, "severity": "info", "heading": a.get("heading"), "source": "adsb.lol (open ADS-B)",
                    "url": f"https://globe.adsb.lol/?icao={a['hex']}",
                    "details": {"Role": a["role"], "Type": a["type"], "Registration": a["registration"],
                                "Altitude (ft)": a["altitude_ft"], "Speed (kt)": a["speed_kt"], "Squawk": a["squawk"],
                                "Emergency": a.get("emergency")}})
    if "conflict" in wanted:
        evs = sorted(s.get("gdelt") or [], key=lambda e: -e["num_sources"])
        for e in evs:
            if _in(bbox, e["lat"], e["lon"]) and len(feats["conflict"]) < 150:
                feats["conflict"].append({
                    "id": e["id"], "layer": "conflict", "lat": e["lat"], "lon": e["lon"],
                    "title": f"{e['category'].replace('_', ' ').title()}: {e['place'].split(',')[0]}",
                    "time": e["date_added"], "severity": "elevated" if e["root_code"] in ("19", "20") else "moderate",
                    "verdict": "news_coded_unverified", "source": "GDELT (machine-coded from news)", "url": e["source_url"],
                    "details": {"Actors": f"{e.get('actor1') or '?'} → {e.get('actor2') or '?'}", "Sources": e["num_sources"],
                                "Articles": e["num_articles"], "Tone": e["tone"], "Precision": e["precision"]}})
    if "quakes" in wanted:
        for q in s.get("quakes") or []:
            if _in(bbox, q["lat"], q["lon"]):
                m = q.get("magnitude") or 0
                feats["quakes"].append({
                    "id": q["id"], "layer": "quakes", "lat": q["lat"], "lon": q["lon"], "title": f"M{m} {q['place']}",
                    "time": q["time"], "severity": "critical" if m >= 7 else "high" if m >= 6 else "moderate",
                    "source": "USGS", "url": q["url"],
                    "details": {"Magnitude": m, "Depth (km)": q["depth_km"], "Tsunami flag": q["tsunami"], "PAGER alert": q["alert"]}})

    tasks = {}
    if "chokepoints" in wanted:
        from osint.tools.military import get_chokepoint_status
        tasks["chokepoints"] = get_chokepoint_status()
    if "hotspots" in wanted:
        from osint.tools.conflict import get_hotspot_escalation
        tasks["hotspots"] = get_hotspot_escalation()
    if "disasters" in wanted:
        tasks["gdacs"] = safe_fetch(r, "GDACS", hazards.GDACS_URL, hazards.gdacs_events())
    if "outages" in wanted:
        tasks["outages"] = safe_fetch(r, "IODA", world.IODA_EVENTS_URL, world.ioda_outages(None, 2))
    if "fires" in wanted and bbox:
        tasks["fires"] = safe_fetch(r, "NASA FIRMS", "https://firms.modaps.eosdis.nasa.gov", hazards.firms_hotspots(bbox, 1))
    if "ships" in wanted and bbox:
        tasks["ships"] = safe_fetch(r, "aisstream.io", world.AISSTREAM_URL, world.ais_snapshot(bbox, 15))
    done = dict(zip(tasks, await asyncio.gather(*tasks.values()))) if tasks else {}

    if "chokepoints" in done:
        cp = json.loads(done["chokepoints"])
        r.sources += cp["sources"]
        by_name = {v["name"]: (k, v) for k, v in geo.CHOKEPOINTS.items()}
        for x in (cp.get("data") or {}).get("chokepoints", []):
            cid, meta = by_name.get(x["name"], (None, None))
            if not meta or not _in(bbox, meta["lat"], meta["lon"]):
                continue
            sev = {"severe_disruption": "critical", "disrupted": "high", "elevated_traffic": "moderate"}.get(x.get("status"), "low")
            feats["chokepoints"].append({
                "id": f"cp-{cid}", "layer": "chokepoints", "lat": meta["lat"], "lon": meta["lon"],
                "title": f"{x['name']}: {str(x.get('status', 'no data')).replace('_', ' ')}", "time": x.get("latest_date"),
                "severity": sev, "source": "IMF PortWatch",
                "details": {"Transits/day (last 7d)": x.get("avg_daily_transits_last_7d"),
                            "Same week last year": x.get("avg_daily_transits_same_week_last_year"),
                            "Change vs last year %": x.get("change_vs_last_year_pct"),
                            "Tankers/day (last 7d)": x.get("tankers_last_7d_avg")}})
    if "hotspots" in done:
        hs = json.loads(done["hotspots"])
        r.sources += [x for x in hs["sources"] if x["name"] not in {y["name"] for y in r.sources}]
        for x in (hs.get("data") or {}).get("hotspots", []):
            h = geo.HOTSPOTS[x["hotspot"]]
            if not _in(bbox, h["lat"], h["lon"]):
                continue
            sc = x["score"]
            feats["hotspots"].append({
                "id": f"hs-{x['hotspot']}", "layer": "hotspots", "lat": h["lat"], "lon": h["lon"],
                "title": f"{x['name']}: escalation {sc}/5", "time": None,
                "severity": "critical" if sc >= 4.2 else "high" if sc >= 3.5 else "elevated" if sc >= 2.8 else "low",
                "source": "SoldierIQ heuristic (news, strikes, events, air)", "radius_km": h["radius_km"],
                "details": {"Score": sc, "Baseline": x["baseline"], "Trend": x["trend_hint"].replace("_", " "),
                            **{k.replace("_", " ").title(): v for k, v in x["counts"].items()}}})
    if "disasters" in wanted:
        for g in done.get("gdacs") or []:
            if g.get("lat") is not None and _in(bbox, g["lat"], g["lon"]):
                feats["disasters"].append({
                    "id": f"gdacs-{g['id']}", "layer": "disasters", "lat": g["lat"], "lon": g["lon"],
                    "title": f"{(g['type'] or '').replace('_', ' ').title()}: {g['name']}", "time": g.get("from"),
                    "severity": "critical" if (g.get("alert_level") or "").lower() == "red" else "high",
                    "source": "GDACS", "url": g.get("url"),
                    "details": {"Alert level": g.get("alert_level"), "Country": g.get("country"), "Until": g.get("to")}})
    if "outages" in wanted:
        seen = set()
        for o in done.get("outages") or []:
            iso2 = (o["entity"] or "").split("/")[-1]
            c = geo.country(iso2)
            if not c or iso2 in seen or o["score"] < 500:
                continue
            lon, lat = c["label"]
            if not _in(bbox, lat, lon):
                continue
            seen.add(iso2)
            feats["outages"].append({
                "id": f"out-{iso2}", "layer": "outages", "lat": lat, "lon": lon,
                "title": f"Internet disruption: {c['name']}", "time": o["start"],
                "severity": "critical" if o["score"] >= 10000 else "high" if o["score"] >= 1000 else "moderate",
                "source": "IODA (Georgia Tech)", "url": f"https://ioda.inetintel.cc.gatech.edu/country/{iso2}",
                "details": {"Signal": o["datasource"], "Score": o["score"], "Duration (h)": o["duration_hours"]}})
    for i, f in enumerate(sorted(done.get("fires") or [], key=lambda f: -f["frp_mw"])[:120]):
        feats["fires"].append({
            "id": f"fire-{i}", "layer": "fires", "lat": f["lat"], "lon": f["lon"], "title": f"Thermal anomaly ({f['frp_mw']} MW)",
            "time": f["acquired"], "severity": "high" if f["frp_mw"] >= 50 else "moderate", "source": "NASA FIRMS VIIRS",
            "details": {"Fire power (MW)": f["frp_mw"], "Brightness (K)": f["brightness_k"], "Confidence": f["confidence"],
                        "Day/night": f["day_night"]}})
    for v in done.get("ships") or []:
        if v.get("lat") is None:
            continue
        cat = v.get("category", "unknown")
        feats["ships"].append({
            "id": f"ship-{v['mmsi']}", "layer": "ships", "lat": v["lat"], "lon": v["lon"],
            "title": f"{v.get('name') or v['mmsi']} · {cat.replace('_', ' ')}", "time": v.get("time"),
            "severity": "elevated" if cat in ("military", "law_enforcement") else "info", "heading": v.get("heading"),
            "source": "aisstream.io (AIS)", "url": f"https://www.marinetraffic.com/en/ais/details/ships/mmsi:{v['mmsi']}",
            "details": {"MMSI": v["mmsi"], "Category": cat, "Speed (kt)": v.get("speed_kt"), "Destination": v.get("destination")}})

    # Cap the total so the card stays light: keep the most severe first, per layer fairly.
    rank = {"critical": 0, "high": 1, "elevated": 2, "moderate": 3, "low": 4, "info": 5}
    per_layer = max(20, MAX_FEATURES // max(1, len(wanted)))
    features = []
    for k in wanted:
        features += sorted(feats[k], key=lambda f: rank.get(f["severity"], 9))[:per_layer]

    notes = list(dict.fromkeys(r.notes))
    if skipped:
        notes.append(f"Layers not available on this server (missing API key): {', '.join(skipped)}.")
    if "aircraft" in wanted:
        notes.append("Aircraft come from open ADS-B: military aircraft with transponders off are not shown.")
    if "strikes" in wanted:
        notes.append("Strike icons are reports from public Telegram channels; tap one to see its corroboration verdict.")
    return {
        "type": "map",
        "title": title or f"{label.title() if label == 'global' else label}: intelligence overlay",
        "region": label,
        "bbox": list(bbox) if bbox else None,
        "hours": hours,
        "layers": [{"id": k, "label": LAYERS[k]["label"], "icon": LAYERS[k]["icon"],
                    "count": sum(1 for f in features if f["layer"] == k)} for k in wanted],
        "features": features,
        "sources": [{"name": x["name"], "ok": x["ok"], "fetched_at": x.get("fetched_at")} for x in r.sources],
        "notes": notes,
    }
