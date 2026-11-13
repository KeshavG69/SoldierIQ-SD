"""Humanitarian and health: displacement, asylum flows, disease outbreaks."""

from __future__ import annotations

import asyncio
from typing import Optional

from osint import geo
from osint.core import Result, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import world


def _num(v) -> int:
    try:
        return int(str(v).replace(",", "")) if v not in (None, "-", "") else 0
    except ValueError:
        return 0


@osint_tool(group="humanitarian", tier=2)
async def get_displacement_data(country: str) -> str:
    """Forced displacement for a country from UNHCR, by year: refugees and asylum seekers who fled it, people
    displaced inside it (IDPs), returnees, and refugees it hosts from elsewhere.

    Args:
        country: Country name or ISO code.
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_displacement_data", f"Unknown country {country!r}")
    r = Result("get_displacement_data")
    origin, hosted = await asyncio.gather(
        safe_fetch(r, "UNHCR population (origin)", world.UNHCR_POP_URL, world.unhcr_population(c["iso3"], "origin")),
        safe_fetch(r, "UNHCR population (hosted)", world.UNHCR_POP_URL, world.unhcr_population(c["iso3"], "asylum")))

    def rows(items):
        out = {}
        for it in items or []:
            y = it.get("year")
            cur = out.setdefault(y, {"year": y, "refugees": 0, "asylum_seekers": 0, "idps": 0, "returned_refugees": 0,
                                     "stateless": 0})
            for k in ("refugees", "asylum_seekers", "idps", "returned_refugees", "stateless"):
                cur[k] += _num(it.get(k))
        return sorted(out.values(), key=lambda x: x["year"])

    r.data = {"country": geo.country_brief(c), "from_country": rows(origin), "hosted_in_country": rows(hosted)}
    r.notes.append("UNHCR statistics are annual (mid-year and end-year) and lag recent events by months.")
    return r.to_json()


@osint_tool(group="humanitarian", tier=2)
async def get_cross_border_arrivals(country: str) -> str:
    """Where people fleeing a country are going: new asylum applications lodged by its citizens, by destination
    country and year (UNHCR), showing which neighbors and partners absorb the outflow.

    Args:
        country: Country of origin, name or ISO code.
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_cross_border_arrivals", f"Unknown country {country!r}")
    r = Result("get_cross_border_arrivals")
    items = await safe_fetch(r, "UNHCR asylum applications", world.UNHCR_ASYLUM_URL, world.unhcr_asylum_applications(c["iso3"]))
    by_year: dict[int, dict] = {}
    for it in items or []:
        y = it.get("year")
        dest = it.get("coa_name") or it.get("coa")
        n = _num(it.get("applied"))
        if not n:
            continue
        by_year.setdefault(y, {}).setdefault(dest, 0)
        by_year[y][dest] += n
    years = []
    for y in sorted(by_year):
        dests = sorted(by_year[y].items(), key=lambda x: -x[1])
        years.append({"year": y, "total": sum(v for _, v in dests),
                      "top_destinations": [{"country": d, "applications": v} for d, v in dests[:10]]})
    r.data = {"origin": geo.country_brief(c), "by_year": years}
    r.notes.append("Annual UNHCR data; the current year is partial or missing.")
    return r.to_json()


@osint_tool(group="humanitarian", tier=2)
async def get_health_signals(country: Optional[str] = None, limit: int = 15) -> str:
    """Disease outbreaks reported by the World Health Organization (Disease Outbreak News), newest first, with
    summary and link, optionally filtered to one country.

    Args:
        country: Optional country name or ISO code.
        limit: Maximum reports (default 15).
    """
    c = geo.country(country) if country else None
    if country and not c:
        return unavailable("get_health_signals", f"Unknown country {country!r}")
    r = Result("get_health_signals")
    items = await safe_fetch(r, "WHO Disease Outbreak News", world.WHO_DON_URL, world.who_outbreaks(50))
    if c:
        names = [n.lower() for n in (c["name"], c["name_long"], c["admin"])]
        items = [i for i in items or [] if any(n in (i["title"] or "").lower() or n in (i["summary"] or "").lower() for n in names)]
    r.data = {"country": c["name"] if c else None, "outbreaks": (items or [])[: max(1, limit)]}
    return r.to_json()
