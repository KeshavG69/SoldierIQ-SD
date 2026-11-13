"""Geography for the OSINT tools: countries, theaters, hotspots, chokepoints.

Country shapes come from Natural Earth (public domain), simplified; see
data/SOURCES.txt. Theater boxes, hotspots and chokepoints are our own
reference lists.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA = Path(__file__).parent / "data"


@lru_cache(maxsize=1)
def _countries() -> list[dict]:
    return json.loads((_DATA / "countries.json").read_text())


@lru_cache(maxsize=1)
def _index() -> dict[str, dict]:
    idx: dict[str, dict] = {}
    for c in _countries():
        for key in (c["iso2"], c["iso3"], c["name"], c["name_long"], c["admin"]):
            if key:
                idx[key.lower()] = c
    aliases = {
        "usa": "US", "united states of america": "US", "america": "US", "uk": "GB", "britain": "GB",
        "great britain": "GB", "russia": "RU", "south korea": "KR", "north korea": "KP", "iran": "IR",
        "syria": "SY", "uae": "AE", "emirates": "AE", "gaza": "PS", "west bank": "PS", "palestine": "PS",
        "ivory coast": "CI", "drc": "CD", "dr congo": "CD", "congo-kinshasa": "CD", "burma": "MM",
        "czech republic": "CZ", "turkey": "TR", "türkiye": "TR", "turkiye": "TR", "vatican": "VA",
        "taiwan": "TW", "laos": "LA", "vietnam": "VN", "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ",
        "moldova": "MD", "macedonia": "MK", "eswatini": "SZ", "swaziland": "SZ", "east timor": "TL",
    }
    for alias, iso2 in aliases.items():
        if iso2.lower() in idx:
            idx[alias] = idx[iso2.lower()]
    return idx


def country(query: Optional[str]) -> Optional[dict]:
    """Resolve an ISO2/ISO3 code or country name to its record."""
    if not query:
        return None
    return _index().get(query.strip().lower())


def all_countries() -> list[dict]:
    return _countries()


def country_brief(c: dict) -> dict:
    return {"iso2": c["iso2"], "iso3": c["iso3"], "name": c["name"], "subregion": c["subregion"]}


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def in_country(lon: float, lat: float, c: dict) -> bool:
    w, s, e, n = c["bbox"]
    if not (w <= lon <= e and s <= lat <= n):
        return False
    return any(_in_ring(lon, lat, ring) for ring in c["polygons"])


def country_at(lon: float, lat: float) -> Optional[dict]:
    for c in _countries():
        if in_country(lon, lat, c):
            return c
    return None


def in_bbox(lon: float, lat: float, bbox: tuple[float, float, float, float]) -> bool:
    w, s, e, n = bbox
    if w <= e:
        return w <= lon <= e and s <= lat <= n
    return (lon >= w or lon <= e) and s <= lat <= n  # crosses the antimeridian


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def parse_bbox(bbox: Optional[str]) -> Optional[tuple[float, float, float, float]]:
    """'west,south,east,north' -> tuple, or None."""
    if not bbox:
        return None
    try:
        w, s, e, n = (float(x) for x in bbox.split(","))
    except ValueError:
        return None
    if not (-180 <= w <= 180 and -180 <= e <= 180 and -90 <= s <= n <= 90):
        return None
    return (w, s, e, n)


def region_bbox(region: Optional[str]) -> tuple[Optional[tuple], str]:
    """Resolve a theater id, country, or 'w,s,e,n' string to a bbox and label."""
    if not region:
        return None, "global"
    t = THEATERS.get(region.strip().lower().replace(" ", "-"))
    if t:
        return t["bbox"], t["name"]
    c = country(region)
    if c:
        return tuple(c["bbox"]), c["name"]
    b = parse_bbox(region)
    if b:
        return b, f"bbox {region}"
    return None, region


# ── Theaters (west, south, east, north) and posture thresholds ───────────────
# Thresholds are counts of military aircraft seen on open ADS-B in the box.
# Many military aircraft fly without transponders, so these are lower bounds.

THEATERS: dict[str, dict] = {
    "iran": {"name": "Iran / Persian Gulf", "bbox": (43.0, 23.0, 64.0, 40.5), "elevated": 8, "critical": 20},
    "levant": {"name": "Israel / Lebanon / Syria", "bbox": (33.0, 29.0, 42.5, 37.5), "elevated": 6, "critical": 14},
    "iraq": {"name": "Iraq", "bbox": (38.5, 29.0, 48.8, 37.5), "elevated": 5, "critical": 12},
    "red-sea": {"name": "Red Sea / Yemen / Horn of Africa", "bbox": (32.0, 10.5, 54.0, 22.5), "elevated": 4, "critical": 10},
    "arabian-peninsula": {"name": "Arabian Peninsula", "bbox": (34.5, 12.0, 60.0, 32.0), "elevated": 10, "critical": 25},
    "east-med": {"name": "Eastern Mediterranean", "bbox": (24.0, 31.0, 36.0, 38.0), "elevated": 4, "critical": 10},
    "black-sea": {"name": "Black Sea / Ukraine", "bbox": (26.0, 40.5, 42.0, 52.5), "elevated": 4, "critical": 10},
    "baltic": {"name": "Baltic", "bbox": (10.0, 53.0, 32.0, 66.0), "elevated": 5, "critical": 12},
    "taiwan": {"name": "Taiwan Strait", "bbox": (115.0, 19.0, 128.0, 29.0), "elevated": 6, "critical": 15},
    "south-china-sea": {"name": "South China Sea", "bbox": (105.0, 3.0, 121.0, 23.0), "elevated": 6, "critical": 15},
    "korea": {"name": "Korean Peninsula", "bbox": (124.0, 33.0, 132.0, 43.0), "elevated": 5, "critical": 12},
    "sahel": {"name": "Sahel", "bbox": (-17.0, 10.0, 25.0, 22.0), "elevated": 4, "critical": 10},
    "afghanistan-pakistan": {"name": "Afghanistan / Pakistan", "bbox": (60.0, 23.5, 78.0, 38.5), "elevated": 6, "critical": 14},
}

# ── Curated hotspots (lat, lon, radius_km, baseline 1-5) ─────────────────────

HOTSPOTS: dict[str, dict] = {
    "strait_of_hormuz": {"name": "Strait of Hormuz", "lat": 26.6, "lon": 56.3, "radius_km": 250, "baseline": 4, "countries": ["IR", "OM", "AE"]},
    "tehran": {"name": "Tehran", "lat": 35.7, "lon": 51.4, "radius_km": 200, "baseline": 3, "countries": ["IR"]},
    "south_lebanon": {"name": "Southern Lebanon", "lat": 33.3, "lon": 35.4, "radius_km": 60, "baseline": 4, "countries": ["LB", "IL"]},
    "gaza": {"name": "Gaza", "lat": 31.45, "lon": 34.4, "radius_km": 40, "baseline": 5, "countries": ["PS", "IL"]},
    "west_bank": {"name": "West Bank", "lat": 32.0, "lon": 35.25, "radius_km": 50, "baseline": 3, "countries": ["PS"]},
    "damascus": {"name": "Damascus / southern Syria", "lat": 33.5, "lon": 36.3, "radius_km": 120, "baseline": 3, "countries": ["SY"]},
    "northeast_syria": {"name": "Northeast Syria", "lat": 36.5, "lon": 40.5, "radius_km": 200, "baseline": 3, "countries": ["SY", "IQ", "TR"]},
    "baghdad": {"name": "Baghdad", "lat": 33.3, "lon": 44.4, "radius_km": 150, "baseline": 3, "countries": ["IQ"]},
    "bab_el_mandeb": {"name": "Bab el-Mandeb / Red Sea", "lat": 13.0, "lon": 43.3, "radius_km": 300, "baseline": 4, "countries": ["YE", "DJ", "ER"]},
    "sanaa": {"name": "Sanaa / northern Yemen", "lat": 15.4, "lon": 44.2, "radius_km": 250, "baseline": 4, "countries": ["YE"]},
    "eastern_ukraine": {"name": "Eastern Ukraine front", "lat": 48.3, "lon": 37.8, "radius_km": 250, "baseline": 5, "countries": ["UA", "RU"]},
    "black_sea": {"name": "Black Sea / Crimea", "lat": 44.8, "lon": 34.0, "radius_km": 300, "baseline": 4, "countries": ["UA", "RU"]},
    "kaliningrad": {"name": "Kaliningrad / Suwalki", "lat": 54.7, "lon": 21.5, "radius_km": 200, "baseline": 2, "countries": ["RU", "LT", "PL"]},
    "taiwan_strait": {"name": "Taiwan Strait", "lat": 24.5, "lon": 119.8, "radius_km": 300, "baseline": 3, "countries": ["TW", "CN"]},
    "south_china_sea": {"name": "Spratly Islands", "lat": 10.0, "lon": 114.0, "radius_km": 500, "baseline": 3, "countries": ["CN", "PH", "VN"]},
    "korean_dmz": {"name": "Korean DMZ", "lat": 38.0, "lon": 127.0, "radius_km": 150, "baseline": 3, "countries": ["KP", "KR"]},
    "kashmir": {"name": "Kashmir LoC", "lat": 34.0, "lon": 74.5, "radius_km": 200, "baseline": 3, "countries": ["IN", "PK"]},
    "khartoum": {"name": "Khartoum / Darfur", "lat": 14.0, "lon": 28.0, "radius_km": 700, "baseline": 5, "countries": ["SD"]},
    "eastern_drc": {"name": "Eastern DRC (Kivu)", "lat": -1.5, "lon": 29.0, "radius_km": 250, "baseline": 4, "countries": ["CD", "RW"]},
    "central_sahel": {"name": "Central Sahel (Mali/Burkina/Niger)", "lat": 14.5, "lon": -1.5, "radius_km": 700, "baseline": 4, "countries": ["ML", "BF", "NE"]},
    "somalia": {"name": "Somalia", "lat": 3.0, "lon": 45.0, "radius_km": 600, "baseline": 4, "countries": ["SO"]},
    "libya": {"name": "Libya (Tripoli)", "lat": 32.9, "lon": 13.2, "radius_km": 300, "baseline": 2, "countries": ["LY"]},
    "myanmar": {"name": "Myanmar", "lat": 21.0, "lon": 96.0, "radius_km": 600, "baseline": 4, "countries": ["MM"]},
    "haiti": {"name": "Port-au-Prince", "lat": 18.55, "lon": -72.3, "radius_km": 80, "baseline": 4, "countries": ["HT"]},
    "venezuela": {"name": "Venezuela / Caribbean", "lat": 10.5, "lon": -66.9, "radius_km": 400, "baseline": 3, "countries": ["VE"]},
}

# ── Maritime chokepoints (PortWatch names where available) ───────────────────

CHOKEPOINTS: dict[str, dict] = {
    "hormuz": {"name": "Strait of Hormuz", "portwatch": "Strait of Hormuz", "lat": 26.57, "lon": 56.25},
    "bab_el_mandeb": {"name": "Bab el-Mandeb Strait", "portwatch": "Bab el-Mandeb Strait", "lat": 12.6, "lon": 43.4},
    "suez": {"name": "Suez Canal", "portwatch": "Suez Canal", "lat": 30.6, "lon": 32.35},
    "malacca": {"name": "Malacca Strait", "portwatch": "Malacca Strait", "lat": 2.5, "lon": 101.3},
    "panama": {"name": "Panama Canal", "portwatch": "Panama Canal", "lat": 9.1, "lon": -79.7},
    "bosporus": {"name": "Bosporus Strait", "portwatch": "Bosporus Strait", "lat": 41.1, "lon": 29.05},
    "gibraltar": {"name": "Gibraltar Strait", "portwatch": "Gibraltar Strait", "lat": 35.95, "lon": -5.6},
    "taiwan_strait": {"name": "Taiwan Strait", "portwatch": "Taiwan Strait", "lat": 24.5, "lon": 119.5},
    "dover": {"name": "Dover Strait", "portwatch": "Dover Strait", "lat": 51.0, "lon": 1.5},
    "cape_of_good_hope": {"name": "Cape of Good Hope", "portwatch": "Cape of Good Hope", "lat": -34.4, "lon": 18.5},
}

# ── Known nuclear test sites ────────────────────────────────────────────────

TEST_SITES: dict[str, dict] = {
    "punggye_ri": {"name": "Punggye-ri (DPRK)", "lat": 41.28, "lon": 129.08, "country": "KP"},
    "lop_nur": {"name": "Lop Nur (China)", "lat": 41.73, "lon": 88.36, "country": "CN"},
    "novaya_zemlya": {"name": "Novaya Zemlya (Russia)", "lat": 73.37, "lon": 54.78, "country": "RU"},
    "semipalatinsk": {"name": "Semipalatinsk (Kazakhstan, closed)", "lat": 50.07, "lon": 78.43, "country": "KZ"},
    "nevada": {"name": "Nevada National Security Site (US)", "lat": 37.12, "lon": -116.05, "country": "US"},
    "pokhran": {"name": "Pokhran (India)", "lat": 27.07, "lon": 71.72, "country": "IN"},
    "ras_koh": {"name": "Ras Koh / Chagai (Pakistan)", "lat": 28.8, "lon": 64.95, "country": "PK"},
    "fordow": {"name": "Fordow (Iran, enrichment site)", "lat": 34.88, "lon": 50.99, "country": "IR"},
}
