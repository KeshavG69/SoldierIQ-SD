"""Shared signal gathering for the composite tools (hotspots, convergence,
focal points, alert digest, country risk). Each gatherer records its source
outcome on the Result so the composite tool reports partial data honestly."""

from __future__ import annotations

import asyncio
from typing import Optional

from osint import geo
from osint.core import Result, safe_fetch
from osint.sources import flights, gdelt, hazards, news, telegram


async def conflict_gdelt(r: Result, hours: float = 6, min_sources: int = 1) -> list[dict]:
    """GDELT assault/clash/mass-violence events at city precision with >= min_sources sources."""
    evs = await safe_fetch(r, "GDELT 2.0 event export", gdelt.LASTUPDATE_URL, gdelt.recent_events(hours))
    if not evs:
        return []
    return [e for e in evs if e["root_code"] in gdelt.CONFLICT_ROOTS and e["precision"] in ("world_city", "us_state", "city")
            and e["num_sources"] >= min_sources]


async def strikes(r: Result, hours: float = 24) -> list[dict]:
    try:
        posts, status = await telegram.many_channels(telegram.STRIKE_CHANNELS)
    except Exception:  # noqa: BLE001
        posts, status = [], []
    ok = sum(1 for s in status if s["ok"])
    r.source("Telegram public channels", "https://t.me/s/", None, ok=ok > 0,
             error="" if ok else "no channel could be read")
    if status:
        r.sources[-1]["channels_read"] = f"{ok}/{len(status)}"
    return telegram.strike_reports(posts, hours)


async def aircraft(r: Result) -> list[dict]:
    acs = await safe_fetch(r, "adsb.lol military feed", flights.ADSB_MIL_URL, flights.military_aircraft())
    return [a for a in (acs or []) if not a["on_ground"]]


async def quakes(r: Result) -> list[dict]:
    return await safe_fetch(r, "USGS earthquakes (M4.5+, 7 days)", hazards.USGS_URL, hazards.earthquakes("4.5_week")) or []


async def headlines(r: Result, outlets: Optional[list[dict]] = None, hours: float = 24) -> list[dict]:
    items, status = await news.read_all_feeds(outlets)
    ok = sum(1 for s in status if s["ok"])
    r.source("News RSS register", "", None, ok=ok > 0, error="" if ok else "no feed could be read")
    r.sources[-1]["feeds_read"] = f"{ok}/{len(status)}"
    return news.published_after(items, hours)


async def gather(r: Result, *, gdelt_hours: float = 6, strike_hours: float = 24, news_hours: float = 24,
                 want=("gdelt", "strikes", "aircraft", "quakes", "news")) -> dict:
    tasks = {}
    if "gdelt" in want:
        tasks["gdelt"] = conflict_gdelt(r, gdelt_hours)
    if "strikes" in want:
        tasks["strikes"] = strikes(r, strike_hours)
    if "aircraft" in want:
        tasks["aircraft"] = aircraft(r)
    if "quakes" in want:
        tasks["quakes"] = quakes(r)
    if "news" in want:
        tasks["news"] = headlines(r, hours=news_hours)
    values = await asyncio.gather(*tasks.values())
    return dict(zip(tasks.keys(), values))


def within(items: list[dict], lat: float, lon: float, radius_km: float) -> list[dict]:
    out = []
    for i in items:
        if i.get("lat") is None or i.get("lon") is None:
            continue
        if geo.haversine_km(lat, lon, i["lat"], i["lon"]) <= radius_km:
            out.append(i)
    return out


def mentions(items: list[dict], terms: list[str]) -> list[dict]:
    low = [t.lower() for t in terms if t]
    return [i for i in items if any(t in (i.get("title") or "").lower() for t in low)]


def fips_to_iso2(fips: str) -> Optional[str]:
    return FIPS_ISO2.get(fips)


# GDELT uses FIPS 10-4 country codes. Mapping for the codes that differ from ISO2
# in the regions we cover most; identical codes fall through.
FIPS_ISO2 = {
    "IZ": "IQ", "IS": "IL", "LE": "LB", "SY": "SY", "IR": "IR", "YM": "YE", "SA": "SA", "BA": "BH", "QA": "QA",
    "AE": "AE", "KU": "KW", "MU": "OM", "JO": "JO", "TU": "TR", "UP": "UA", "RS": "RU", "BO": "BY", "GM": "DE",
    "UK": "GB", "FR": "FR", "SP": "ES", "PO": "PT", "PL": "PL", "EN": "EE", "LG": "LV", "LH": "LT", "CH": "CN",
    "TW": "TW", "JA": "JP", "KS": "KR", "KN": "KP", "RP": "PH", "VM": "VN", "BM": "MM", "IN": "IN", "PK": "PK",
    "AF": "AF", "BG": "BD", "CE": "LK", "NP": "NP", "SU": "SD", "OD": "SS", "ET": "ET", "SO": "SO", "KE": "KE",
    "CG": "CD", "CF": "CG", "RW": "RW", "UG": "UG", "NI": "NG", "ML": "ML", "UV": "BF", "NG": "NE", "CD": "TD",
    "LY": "LY", "EG": "EG", "AG": "DZ", "MO": "MA", "TS": "TN", "MX": "MX", "VE": "VE", "CO": "CO", "HA": "HT",
    "BR": "BR", "AR": "AR", "US": "US", "CA": "CA", "AS": "AU", "NZ": "NZ", "GZ": "PS", "WE": "PS", "AJ": "AZ",
    "AM": "AM", "GG": "GE", "KZ": "KZ", "UZ": "UZ", "TI": "TJ", "TX": "TM", "KG": "KG", "SF": "ZA", "MZ": "MZ",
    "ZI": "ZW", "AO": "AO", "CM": "CM", "DJ": "DJ", "ER": "ER", "LI": "LR", "SL": "SL", "GH": "GH", "IV": "CI",
    "SG": "SN", "MA": "MG", "IT": "IT", "GR": "GR", "RO": "RO", "HU": "HU", "EZ": "CZ", "LO": "SK", "SW": "SE",
    "FI": "FI", "NO": "NO", "DA": "DK", "NL": "NL", "BE": "BE", "SZ": "CH", "AU": "AT", "EI": "IE", "MD": "MD",
    "MK": "MK", "RI": "RS", "BK": "BA", "HR": "HR", "SI": "SI", "AL": "AL", "CY": "CY", "TH": "TH", "MY": "MY",
    "ID": "ID", "CB": "KH", "LA": "LA", "MG": "MN",
}
