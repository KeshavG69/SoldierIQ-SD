"""Infrastructure: internet outages, cable cascade, chokepoint dependencies,
energy, aviation."""

from __future__ import annotations

import asyncio
from typing import Optional

from osint import geo
from osint.core import Result, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import world


@osint_tool(group="infrastructure", tier=1)
async def get_infrastructure_status(country: Optional[str] = None, days: int = 3) -> str:
    """Internet disruption by country from IODA (BGP routing, active probing and Google traffic signals),
    ranked by severity, with start time and duration. Use it to spot shutdowns, cable cuts and
    strike damage to telecoms.

    Args:
        country: Optional country name or ISO code. Omit for the worst outages worldwide.
        days: Look-back (1-14, default 3).
    """
    c = geo.country(country) if country else None
    if country and not c:
        return unavailable("get_infrastructure_status", f"Unknown country {country!r}")
    r = Result("get_infrastructure_status")
    outages = await safe_fetch(r, "IODA (Georgia Tech)", world.IODA_EVENTS_URL,
                               world.ioda_outages(c["iso2"] if c else None, max(1, min(int(days), 14))))
    if outages is None:
        return r.to_json()
    by_country: dict[str, dict] = {}
    for o in outages:
        k = o["name"] or o["entity"]
        cur = by_country.setdefault(k, {"country": k, "events": 0, "max_score": 0, "signals": set(), "latest_start": None})
        cur["events"] += 1
        cur["max_score"] = max(cur["max_score"], o["score"])
        cur["signals"].add(o["datasource"])
        cur["latest_start"] = max(filter(None, [cur["latest_start"], o["start"]]), default=None)
    rows = []
    for v in by_country.values():
        v["signals"] = sorted(v["signals"])
        v["severity"] = "major" if v["max_score"] >= 10000 else "significant" if v["max_score"] >= 1000 else "minor"
        rows.append(v)
    rows.sort(key=lambda x: -x["max_score"])
    r.data = {"country": c["name"] if c else None, "days": days, "countries": rows[:30], "events": outages[:40]}
    r.notes.append("IODA scores are anomaly magnitudes, not user counts. Several signals agreeing (BGP + probing) "
                   "is stronger evidence than one.")
    return r.to_json()


@osint_tool(group="infrastructure", tier=2)
async def simulate_infrastructure_cascade(country: str) -> str:
    """Submarine-cable exposure for a country: which international cables land there, where else each cable
    lands, how many cables the country has in total, and which neighbors share the most cables (the countries
    whose cable damage would also hit this one). A simple dependency view, not a traffic model.

    Args:
        country: Country name or ISO code.
    """
    c = geo.country(country)
    if not c:
        return unavailable("simulate_infrastructure_cascade", f"Unknown country {country!r}")
    r = Result("simulate_infrastructure_cascade")
    data = await safe_fetch(r, "TeleGeography Submarine Cable Map", world.CABLE_COUNTRY_URL.format(slug=""),
                            world.cables_for_country(c["admin"]))
    if data is None and c["name"] != c["admin"]:
        data = await safe_fetch(r, "TeleGeography Submarine Cable Map", "", world.cables_for_country(c["name"]))
    if data is None:
        r.notes.append("No cable record found; landlocked countries have no direct submarine cables.")
        return r.to_json()
    cables = [cb for cb in data.get("cables") or [] if not cb.get("is_planned")]
    shared: dict[str, int] = {}
    rows = []
    me = c["admin"].lower().replace(" ", "-")
    for cb in cables:
        lps = cb.get("landing_points") or []
        countries = set()
        for lp in lps:
            # landing point ids look like "city-name-country-name"; match against known countries
            for cc in geo.all_countries():
                slug = cc["admin"].lower().replace(" ", "-")
                if lp.endswith(slug) and slug != me:
                    countries.add(cc["name"])
        for n in countries:
            shared[n] = shared.get(n, 0) + 1
        rows.append({"cable": cb.get("name"), "ready_for_service": cb.get("rfs_year"), "landing_points": len(set(lps)),
                     "other_countries": sorted(countries)})
    rows.sort(key=lambda x: -(x["ready_for_service"] or 0))
    total = len(rows)
    r.data = {"country": geo.country_brief(c), "active_cables": total,
              "resilience": "low" if total <= 2 else "moderate" if total <= 6 else "high",
              "most_shared_countries": sorted(({"country": k, "shared_cables": v} for k, v in shared.items()),
                                              key=lambda x: -x["shared_cables"])[:12],
              "cables": rows}
    r.notes.append("Terrestrial fiber and satellite links are not included; cable counts are a proxy for redundancy.")
    return r.to_json()


# Approximate oil flows (million barrels/day), EIA "World Oil Transit Chokepoints" and later EIA notes.
CHOKEPOINT_OIL_MBD = {"hormuz": 20.0, "malacca": 23.0, "suez": 7.5, "bab_el_mandeb": 4.0, "bosporus": 3.4,
                      "panama": 2.0, "cape_of_good_hope": 9.0, "dover": 3.0, "gibraltar": 3.0, "taiwan_strait": 2.0}
# Heuristic exposure by region: which chokepoints a country's seaborne energy trade usually crosses.
_EXPOSURE = {
    "gulf_exporter": (["SA", "IR", "IQ", "KW", "AE", "QA", "BH", "OM"], ["hormuz", "bab_el_mandeb", "suez", "malacca"]),
    "east_asia": (["CN", "JP", "KR", "TW", "PH", "VN"], ["hormuz", "malacca", "taiwan_strait"]),
    "south_asia": (["IN", "PK", "BD", "LK"], ["hormuz", "bab_el_mandeb"]),
    "southeast_asia": (["SG", "MY", "TH", "ID"], ["malacca", "hormuz"]),
    "europe": (["GB", "FR", "DE", "IT", "ES", "NL", "BE", "PL", "GR", "PT", "SE", "DK", "FI", "NO", "IE", "AT", "CZ", "RO"],
               ["suez", "bab_el_mandeb", "gibraltar", "dover", "bosporus", "cape_of_good_hope"]),
    "east_med": (["IL", "LB", "SY", "TR", "EG", "CY", "JO"], ["suez", "bab_el_mandeb", "bosporus"]),
    "black_sea": (["UA", "RU", "GE", "BG"], ["bosporus"]),
    "americas": (["US", "CA", "MX", "BR", "AR", "CL", "CO", "PE", "EC"], ["panama", "cape_of_good_hope"]),
    "east_africa": (["KE", "TZ", "SO", "DJ", "ER", "SD", "ET"], ["bab_el_mandeb", "suez"]),
}


@osint_tool(group="infrastructure", tier=2)
async def get_chokepoint_dependencies(country: str) -> str:
    """Which maritime chokepoints a country's seaborne energy and trade typically depend on, with the
    approximate oil volume through each and each chokepoint's current transit status, so the analyst can judge
    the impact of a closure.

    Args:
        country: Country name or ISO code.
    """
    from osint.tools.military import get_chokepoint_status
    import json

    c = geo.country(country)
    if not c:
        return unavailable("get_chokepoint_dependencies", f"Unknown country {country!r}")
    region, cps = next(((k, v[1]) for k, v in _EXPOSURE.items() if c["iso2"] in v[0]), (None, []))
    if not cps:
        return unavailable("get_chokepoint_dependencies",
                           f"No dependency profile for {c['name']} yet; use get_chokepoint_status for all chokepoints")
    r = Result("get_chokepoint_dependencies")
    statuses = await asyncio.gather(*(get_chokepoint_status(cp) for cp in cps))
    rows = []
    for cp, raw in zip(cps, statuses):
        st = json.loads(raw)
        r.sources += st["sources"]
        info = (st.get("data") or {}).get("chokepoints", [{}])[0]
        rows.append({"chokepoint": cp, "name": geo.CHOKEPOINTS[cp]["name"], "oil_flow_mbd_approx": CHOKEPOINT_OIL_MBD.get(cp),
                     "status": info.get("status"), "transit_change_vs_last_year_pct": info.get("change_vs_last_year_pct")})
    r.data = {"country": geo.country_brief(c), "profile": region, "dependencies": rows}
    r.notes.append("Dependencies are a regional heuristic, not customs data; oil volumes are approximate EIA figures. "
                   "Pipelines (e.g. Saudi East-West, UAE Habshan-Fujairah) can bypass Hormuz in part.")
    return r.to_json()


@osint_tool(group="infrastructure", tier=2, requires=("EIA_API_KEY",))
async def get_energy_intelligence() -> str:
    """Energy market signals from the US Energy Information Administration: Brent and WTI crude spot prices,
    Henry Hub gas, and US crude and gasoline inventories, with recent history to show the direction."""
    r = Result("get_energy_intelligence")
    names = list(world.EIA_SERIES)
    vals = await asyncio.gather(*(safe_fetch(r, f"EIA {n}", world.EIA_URL, world.eia_series(n)) for n in names))
    out = {}
    for n, v in zip(names, vals):
        if not v:
            continue
        latest, prev = v[0].get("value"), v[-1].get("value")
        try:
            change = round((float(latest) - float(prev)) / float(prev) * 100, 1)
        except (TypeError, ValueError, ZeroDivisionError):
            change = None
        out[n] = {"latest": v[0], "change_over_window_pct": change, "series": v}
    r.data = out
    return r.to_json()


@osint_tool(group="infrastructure", tier=2)
async def get_aviation_status() -> str:
    """Current US airport disruptions from the FAA National Airspace System status: closures, ground stops,
    ground delay programs and arrival/departure delays with reasons."""
    r = Result("get_aviation_status")
    items = await safe_fetch(r, "FAA NAS Status", world.FAA_URL, world.faa_airport_status())
    if items is None:
        return r.to_json()
    by_kind: dict[str, int] = {}
    for i in items:
        by_kind[i["kind"]] = by_kind.get(i["kind"], 0) + 1
    r.data = {"by_kind": by_kind, "items": items[:60]}
    r.notes.append("US airports only. For military air activity use get_military_posture / get_airspace.")
    return r.to_json()
