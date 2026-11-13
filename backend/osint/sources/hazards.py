"""Natural hazards and physical signals: USGS, GDACS, NASA EONET, NASA FIRMS, Safecast."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from app.settings import settings
from osint.core import SourceError, cached, get_json, get_text, iso

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/{feed}.geojson"
GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/{bbox}/{days}"
SAFECAST_URL = "https://api.safecast.org/measurements.json"


async def earthquakes(feed: str = "4.5_week") -> tuple[list[dict], str]:
    """USGS earthquakes. feed: significant_week | 4.5_day | 4.5_week | 2.5_day | 2.5_week | 4.5_month."""
    allowed = {"significant_week", "significant_month", "4.5_day", "4.5_week", "4.5_month", "2.5_day", "2.5_week", "all_day"}
    if feed not in allowed:
        feed = "4.5_week"

    async def fetch():
        data = await get_json(USGS_URL.format(feed=feed))
        out = []
        for f in data.get("features") or []:
            p, g = f.get("properties") or {}, f.get("geometry") or {}
            coords = g.get("coordinates") or [None, None, None]
            out.append({
                "id": f.get("id"),
                "magnitude": p.get("mag"),
                "place": p.get("place"),
                "time": iso(p["time"] / 1000) if p.get("time") else None,
                "lat": coords[1],
                "lon": coords[0],
                "depth_km": coords[2],
                "tsunami": bool(p.get("tsunami")),
                "alert": p.get("alert"),
                "url": p.get("url"),
            })
        return out

    return await cached(f"usgs:{feed}", 300, fetch)


async def gdacs_events() -> tuple[list[dict], str]:
    """GDACS orange/red disaster alerts (earthquake, cyclone, flood, volcano, drought, wildfire)."""

    async def fetch():
        data = await get_json(GDACS_URL, params={"alertlevel": "Orange;Red"}, timeout=40)
        out = []
        for f in data.get("features") or []:
            p = f.get("properties") or {}
            coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
            out.append({
                "id": f"{p.get('eventtype')}{p.get('eventid')}",
                "type": {"EQ": "earthquake", "TC": "tropical_cyclone", "FL": "flood", "VO": "volcano",
                         "DR": "drought", "WF": "wildfire"}.get(p.get("eventtype"), p.get("eventtype")),
                "name": p.get("name") or p.get("eventname"),
                "alert_level": p.get("alertlevel"),
                "country": p.get("country"),
                "iso3": p.get("iso3"),
                "from": p.get("fromdate"),
                "to": p.get("todate"),
                "lat": coords[1] if isinstance(coords, list) and len(coords) > 1 and not isinstance(coords[0], list) else None,
                "lon": coords[0] if isinstance(coords, list) and coords and not isinstance(coords[0], list) else None,
                "url": (p.get("url") or {}).get("report"),
            })
        return out

    return await cached("gdacs:orange_red", 900, fetch)


async def eonet_events(days: int = 14) -> tuple[list[dict], str]:
    """NASA EONET open natural events (wildfires, storms, volcanoes, sea ice...)."""

    async def fetch():
        data = await get_json(EONET_URL, params={"status": "open", "days": days, "limit": 300})
        out = []
        for e in data.get("events") or []:
            geo = (e.get("geometry") or [{}])[-1]
            coords = geo.get("coordinates") or [None, None]
            point = isinstance(coords, list) and coords and not isinstance(coords[0], list)
            out.append({
                "id": e.get("id"),
                "title": e.get("title"),
                "category": ", ".join(c.get("title", "") for c in e.get("categories") or []),
                "date": geo.get("date"),
                "lat": coords[1] if point else None,
                "lon": coords[0] if point else None,
                "magnitude": geo.get("magnitudeValue"),
                "magnitude_unit": geo.get("magnitudeUnit"),
                "url": e.get("link"),
            })
        return out

    return await cached(f"eonet:{days}", 900, fetch)


async def firms_hotspots(bbox: tuple[float, float, float, float], days: int = 1) -> tuple[list[dict], str]:
    """NASA FIRMS VIIRS thermal anomalies in a bbox (fires, flares, and sometimes strikes)."""
    if not settings.FIRMS_MAP_KEY:
        raise SourceError("FIRMS_MAP_KEY not configured")
    days = max(1, min(int(days), 5))
    w, s, e, n = (round(v, 2) for v in bbox)
    area = f"{w},{s},{e},{n}"

    async def fetch():
        text = await get_text(FIRMS_URL.format(key=settings.FIRMS_MAP_KEY, bbox=area, days=days), timeout=40)
        if text.lstrip().lower().startswith(("invalid", "<")):
            raise SourceError("FIRMS rejected the request (check FIRMS_MAP_KEY)")
        rows = list(csv.DictReader(io.StringIO(text)))
        out = []
        for r in rows:
            try:
                out.append({
                    "lat": float(r["latitude"]),
                    "lon": float(r["longitude"]),
                    "brightness_k": float(r.get("bright_ti4") or 0),
                    "frp_mw": float(r.get("frp") or 0),
                    "confidence": r.get("confidence"),
                    "acquired": f"{r.get('acq_date')}T{(r.get('acq_time') or '0000').zfill(4)[:2]}:{(r.get('acq_time') or '0000').zfill(4)[2:]}:00Z",
                    "day_night": r.get("daynight"),
                })
            except (KeyError, ValueError):
                continue
        return out

    return await cached(f"firms:{area}:{days}", 1800, fetch)


async def radiation_readings(lat: float, lon: float, radius_km: float = 100, hours: int = 72) -> tuple[list[dict], str]:
    """Safecast citizen radiation measurements near a point (CPM, microsieverts/hour)."""
    radius_m = int(min(max(radius_km, 1), 500) * 1000)
    since = datetime.now(timezone.utc).timestamp() - hours * 3600
    since_s = datetime.fromtimestamp(since, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    async def fetch():
        data = await get_json(SAFECAST_URL, params={
            "latitude": lat, "longitude": lon, "distance": radius_m,
            "captured_after": since_s, "per_page": 200, "order": "captured_at desc",
        }, timeout=40)
        out = []
        for m in data or []:
            v, unit = m.get("value"), m.get("unit")
            usv = round(v / 334.0, 4) if unit == "cpm" and v is not None else (v if unit in ("usv", "µSv/h") else None)
            out.append({
                "lat": m.get("latitude"), "lon": m.get("longitude"), "value": v, "unit": unit,
                "usv_per_h": usv, "captured_at": m.get("captured_at"), "device_id": m.get("device_id"),
            })
        return out

    return await cached(f"safecast:{round(lat, 2)}:{round(lon, 2)}:{radius_m}:{hours}", 1800, fetch)
