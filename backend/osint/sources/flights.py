"""Military aircraft from open ADS-B (adsb.lol, community feeders, ODbL data).

adsb.lol's /v2/mil endpoint returns every aircraft its database flags as
military, worldwide. Aircraft flying with transponders off are not in it, so
counts are a lower bound on real activity.
"""

from __future__ import annotations

from typing import Any

from osint.core import cached, get_json

ADSB_MIL_URL = "https://api.adsb.lol/v2/mil"
ATTRIBUTION = "adsb.lol (ODbL)"

# ICAO type designator -> role. Not exhaustive; unknown types are "other".
_ROLE_BY_TYPE: dict[str, str] = {}
for role, types in {
    "tanker": "K35R K35E KC10 KC46 A330 MRTT A332 A310 KC2 A400 IL78 K767 KC30 KC39 L1011",
    "aew": "E3TF E3CF E737 E7WW E2 E2C E2D A50 KJ20 KJ50 SAAB J200 G550 E767 GLF5 E190",
    "isr": "RC35 R135 E8 P8 P3 EP3 U2 RQ4 MQ9 MQ4C Q4 GLEX B350 PC12 DH8 C12 BE20 C208 E6 E6B RJ85 CL60 GL5T",
    "fighter": "F15 F16 F18 F18S F22 F35 EUFI TOR RFAL GRIF SU27 SU30 SU35 MIG29 J10 J11 F5 A10 AV8B",
    "bomber": "B52 B1 B2 TU95 TU22 TU160 H6",
    "transport": "C17 C130 C30J C5 C5M C2 C295 CN35 A400M IL76 Y20 C160 AN12 AN26 C27J KC390 B737 B738 B739 A319 A320 A321 B752 B762 "
                 "B77L B77W C40 C37 C32 C21 GLF4 GLF6 FA7X FA6X F900 LJ35 LJ45 AT76 AT75 A148 T154 F100 E50P E550 E135 E145 "
                 "D228 DHC6 SB39 SF34 P180 C560 C680 C750",
    "helicopter": "H60 UH60 MH60 S70 H47 CH47 V22 H53 CH53 NH90 EC35 EC45 H64 AH64 A139 A169 LYNX MERL PUMA AS32 AS65 EH10 "
                  "MI8 MI17 MI24 KA52 H145 H135 B412 B429",
    "trainer": "TUCA PC21 PC9 PC7 T6 G115 G120 F260 L39 L159 T38 HAWK M346 SR22 GA6C",
    "utility": "C182 C172 TBM9 TBM7 G12T EN48 PA34 PA31",
    "uav": "MQ9 RQ4 MQ4C Q9 HERN TB2 RQ7",
}.items():
    for t in types.split():
        _ROLE_BY_TYPE.setdefault(t, role)


def role_of(type_code: str) -> str:
    if not type_code:
        return "other"
    t = type_code.upper()
    if t in _ROLE_BY_TYPE:
        return _ROLE_BY_TYPE[t]
    for prefix_len in (4, 3, 2):
        if t[:prefix_len] in _ROLE_BY_TYPE:
            return _ROLE_BY_TYPE[t[:prefix_len]]
    return "other"


def _normalize(ac: dict) -> dict | None:
    lat, lon = ac.get("lat"), ac.get("lon")
    if lat is None or lon is None:
        return None
    alt = ac.get("alt_baro")
    return {
        "hex": ac.get("hex"),
        "callsign": (ac.get("flight") or "").strip() or None,
        "registration": ac.get("r"),
        "type": ac.get("t"),
        "role": role_of(ac.get("t") or ""),
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "altitude_ft": None if alt == "ground" else alt,
        "on_ground": alt == "ground",
        "speed_kt": ac.get("gs"),
        "heading": ac.get("track"),
        "squawk": ac.get("squawk"),
        "emergency": ac.get("emergency") if ac.get("emergency") not in (None, "none") else None,
        "seen_s": ac.get("seen"),
    }


POINT_URL = "https://api.adsb.lol/v2/point/{lat}/{lon}/{radius_nm}"


async def coverage_at(lat: float, lon: float, radius_nm: int = 250) -> tuple[int, str]:
    """All aircraft (civil + military) adsb.lol sees around a point: a proxy for receiver coverage."""

    async def fetch():
        data = await get_json(POINT_URL.format(lat=round(lat, 2), lon=round(lon, 2), radius_nm=min(radius_nm, 250)), timeout=30)
        return len(data.get("ac") or [])

    return await cached(f"adsb:cov:{round(lat, 1)}:{round(lon, 1)}:{radius_nm}", 600, fetch)


async def military_aircraft() -> tuple[list[dict], str]:
    """All military-flagged aircraft with a position (cached 2 minutes)."""

    async def fetch() -> list[dict[str, Any]]:
        data = await get_json(ADSB_MIL_URL, timeout=30)
        out = []
        for ac in data.get("ac") or []:
            n = _normalize(ac)
            if n:
                out.append(n)
        return out

    return await cached("adsb:mil", 120, fetch)
