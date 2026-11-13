"""Hazards and physical signals: disasters, population exposure, test-site
seismicity, radiation, NO2 industrial activity."""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.settings import settings
from osint import geo
from osint.core import Result, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import hazards, world


@lru_cache(maxsize=1)
def _cities() -> list[list]:
    return json.loads((Path(__file__).parent.parent / "data" / "cities.json").read_text())


def _exposure(lat: float, lon: float, radius_km: float) -> dict:
    hits = []
    for name, iso2, clat, clon, pop in _cities():
        d = geo.haversine_km(lat, lon, clat, clon)
        if d <= radius_km:
            hits.append({"city": name, "country": iso2, "distance_km": round(d, 1), "population": pop})
    hits.sort(key=lambda x: -x["population"])
    return {"cities_in_radius": len(hits), "population_in_cities": sum(h["population"] for h in hits),
            "largest_cities": hits[:10]}


@osint_tool(group="hazards", tier=1)
async def get_natural_disasters(region: Optional[str] = None, days: int = 7) -> str:
    """Active natural hazards: earthquakes M4.5+ (USGS), red/orange disaster alerts for earthquakes, cyclones,
    floods, volcanoes and droughts (GDACS), and open natural events such as wildfires and storms (NASA EONET).
    With a region and a FIRMS key, also satellite thermal anomalies (fires, flares, and sometimes strikes).

    Args:
        region: Optional country, theater id or "west,south,east,north" box. Omit for worldwide.
        days: Look-back for earthquakes and events (1-30, default 7).
    """
    days = max(1, min(int(days), 30))
    bbox, label = geo.region_bbox(region)
    if region and not bbox:
        return unavailable("get_natural_disasters", f"Could not resolve region {region!r}")
    r = Result("get_natural_disasters")
    feed = "4.5_day" if days <= 1 else "4.5_week" if days <= 7 else "4.5_month"
    q, g, e = await asyncio.gather(
        safe_fetch(r, "USGS earthquakes", hazards.USGS_URL, hazards.earthquakes(feed)),
        safe_fetch(r, "GDACS alerts", hazards.GDACS_URL, hazards.gdacs_events()),
        safe_fetch(r, "NASA EONET", hazards.EONET_URL, hazards.eonet_events(days)),
    )

    def keep(x):
        return bbox is None or (x.get("lat") is not None and geo.in_bbox(x["lon"], x["lat"], bbox))

    c = geo.country(region) if region else None
    gd = [x for x in (g or []) if keep(x) or (c and (x.get("iso3") or "") == c["iso3"])]
    data = {"region": label, "earthquakes": sorted([x for x in (q or []) if keep(x)], key=lambda x: -(x["magnitude"] or 0))[:40],
            "gdacs_alerts": gd[:30], "eonet_events": [x for x in (e or []) if keep(x)][:40]}
    if bbox and settings.FIRMS_MAP_KEY:
        fires = await safe_fetch(r, "NASA FIRMS VIIRS", "https://firms.modaps.eosdis.nasa.gov",
                                 hazards.firms_hotspots(bbox, min(days, 5)))
        if fires is not None:
            strong = sorted(fires, key=lambda f: -f["frp_mw"])
            data["thermal_anomalies"] = {"count": len(fires), "strongest": strong[:30]}
            r.notes.append("Thermal anomalies include wildfires, gas flares and industrial heat; a cluster of strong, "
                           "new anomalies near military or energy sites can indicate strikes.")
    elif bbox:
        r.notes.append("Satellite thermal anomalies are off (FIRMS_MAP_KEY not configured).")
    r.data = data
    return r.to_json()


@osint_tool(group="hazards", tier=1)
async def get_population_exposure(lat: Optional[float] = None, lon: Optional[float] = None, radius_km: float = 50) -> str:
    """Estimate how many people live near a point (cities of 20,000+ within a radius). Without coordinates,
    estimates exposure for current major hazards: earthquakes M6+ (100 km) and red GDACS alerts (radius by type).

    Args:
        lat: Latitude of the point of interest.
        lon: Longitude of the point of interest.
        radius_km: Radius in km (1-500, default 50).
    """
    r = Result("get_population_exposure")
    r.source("Natural Earth populated places (bundled)", "https://www.naturalearthdata.com", None, ok=True)
    if lat is not None and lon is not None:
        radius = max(1.0, min(float(radius_km), 500.0))
        r.data = {"point": [lat, lon], "radius_km": radius, **_exposure(lat, lon, radius)}
    else:
        q, g = await asyncio.gather(
            safe_fetch(r, "USGS earthquakes", hazards.USGS_URL, hazards.earthquakes("4.5_week")),
            safe_fetch(r, "GDACS alerts", hazards.GDACS_URL, hazards.gdacs_events()))
        events = []
        for x in q or []:
            if (x.get("magnitude") or 0) >= 6:
                events.append({"event": f"M{x['magnitude']} earthquake, {x['place']}", "time": x["time"],
                               **_exposure(x["lat"], x["lon"], 100), "radius_km": 100})
        for x in g or []:
            if (x.get("alert_level") or "").lower() == "red" and x.get("lat") is not None:
                rad = {"tropical_cyclone": 200, "flood": 100, "earthquake": 100, "volcano": 30}.get(x["type"], 80)
                events.append({"event": f"{x['type']} {x['name']}", "time": x.get("from"), **_exposure(x["lat"], x["lon"], rad),
                               "radius_km": rad})
        events.sort(key=lambda e: -e["population_in_cities"])
        r.data = {"hazards": events[:15]}
    r.notes.append("Counts only cities of 20,000+ people, so rural populations are missed: treat as a lower bound.")
    return r.to_json()


@osint_tool(group="hazards", tier=1)
async def get_test_site_seismicity(days: int = 30) -> str:
    """Earthquakes near known nuclear test and enrichment sites (Punggye-ri, Lop Nur, Novaya Zemlya, Nevada,
    Pokhran, Ras Koh, Fordow...). Shallow events close to a site are flagged for attention.

    Args:
        days: Look-back (1-30, default 30).
    """
    days = max(1, min(int(days), 30))
    r = Result("get_test_site_seismicity")
    feed = "2.5_week" if days <= 7 else "4.5_month"
    quakes = await safe_fetch(r, "USGS earthquakes", hazards.USGS_URL, hazards.earthquakes(feed))
    if quakes is None:
        return r.to_json()
    sites = []
    for sid, s in geo.TEST_SITES.items():
        near = []
        for q in quakes:
            if q.get("lat") is None:
                continue
            d = geo.haversine_km(s["lat"], s["lon"], q["lat"], q["lon"])
            if d <= 150:
                shallow = (q.get("depth_km") or 99) <= 5
                near.append({**q, "distance_km": round(d, 1),
                             "concern": "high" if d <= 25 and shallow else "medium" if d <= 60 and shallow else "low"})
        sites.append({"site": sid, "name": s["name"], "events_within_150km": len(near),
                      "events": sorted(near, key=lambda x: x["distance_km"])[:10]})
    r.data = {"days": days, "sites": sites, "flagged": [s for s in sites if any(e["concern"] != "low" for e in s["events"])]}
    r.notes.append("A shallow quake near a test site is a reason to check CTBTO and seismology reporting, not evidence of a test. "
                   "USGS feeds only cover M2.5+ for 7 days and M4.5+ for 30 days.")
    return r.to_json()


@osint_tool(group="hazards", tier=1)
async def get_radiation_data(location: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None,
                             radius_km: float = 100, hours: int = 72) -> str:
    """Recent ambient radiation readings near a place from the Safecast citizen network, in counts per minute and
    estimated microsieverts per hour, with the maximum and median. Normal background is roughly 0.05-0.3 uSv/h.

    Args:
        location: Optional test-site id (e.g. fordow, punggye_ri) or country name; ignored if lat/lon are given.
        lat: Latitude.
        lon: Longitude.
        radius_km: Search radius (1-500, default 100).
        hours: Look-back in hours (1-720, default 72).
    """
    if lat is None or lon is None:
        site = geo.TEST_SITES.get((location or "").lower())
        c = geo.country(location) if location else None
        if site:
            lat, lon = site["lat"], site["lon"]
        elif c:
            lon, lat = c["label"]
        else:
            return unavailable("get_radiation_data", "Give lat/lon, a test-site id or a country")
    r = Result("get_radiation_data")
    readings = await safe_fetch(r, "Safecast", hazards.SAFECAST_URL,
                                hazards.radiation_readings(lat, lon, radius_km, max(1, min(int(hours), 720))))
    vals = sorted(x["usv_per_h"] for x in readings or [] if x.get("usv_per_h") is not None)
    r.data = {"point": [lat, lon], "radius_km": radius_km, "readings": len(vals),
              "median_usv_h": vals[len(vals) // 2] if vals else None, "max_usv_h": vals[-1] if vals else None,
              "elevated": bool(vals and vals[-1] >= 1.0), "latest": (readings or [])[:20]}
    if not vals:
        r.notes.append("Safecast has sparse coverage outside Japan, the US and Europe; no readings is not a reading of zero.")
    return r.to_json()


@osint_tool(group="hazards", tier=2, requires=("COPERNICUS_CLIENT_ID", "COPERNICUS_CLIENT_SECRET"))
async def get_no2_activity(region: str, days: int = 30) -> str:
    """Industrial and military-industrial activity signal from satellite: mean tropospheric NO2 over a region
    (Copernicus Sentinel-5P) for the last `days` compared with the same period a year earlier.

    Args:
        region: Country, theater id or "west,south,east,north" box.
        days: Period length (7-90, default 30).
    """
    bbox, label = geo.region_bbox(region)
    if not bbox:
        return unavailable("get_no2_activity", f"Could not resolve region {region!r}")
    days = max(7, min(int(days), 90))
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days)
    r = Result("get_no2_activity")
    now, before = await asyncio.gather(
        safe_fetch(r, "Copernicus Sentinel-5P (current)", world.CDSE_STATS_URL, world.no2_mean(bbox, start, end)),
        safe_fetch(r, "Copernicus Sentinel-5P (year earlier)", world.CDSE_STATS_URL,
                   world.no2_mean(bbox, start - timedelta(days=365), end - timedelta(days=365))))
    cur, prev = (now or {}).get("mean"), (before or {}).get("mean")
    change = round((cur - prev) / prev * 100, 1) if cur and prev else None
    r.data = {"region": label, "period": [start.isoformat(), end.isoformat()], "mean_no2_mol_m2": cur,
              "year_earlier_mol_m2": prev, "change_pct": change,
              "direction": None if change is None else "up" if change >= 10 else "down" if change <= -10 else "flat"}
    r.notes.append("NO2 tracks combustion (industry, traffic, power, fires) and weather; large boxes dilute local changes.")
    return r.to_json()
