"""Military activity: air posture by theater, surges, airspace, ships, chokepoints."""

from __future__ import annotations

import time
from collections import Counter
from typing import Optional

from osint import geo
from osint.core import Result, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import flights, world

ADSB_NOTE = ("Counts come from open ADS-B (adsb.lol). Aircraft with transponders off are invisible, "
             "so these are minimums, not totals.")


def _role_counts(acs: list[dict]) -> dict[str, int]:
    return dict(Counter(a["role"] for a in acs).most_common())


def _posture(theater_id: str, t: dict, acs: list[dict]) -> dict:
    inside = [a for a in acs if geo.in_bbox(a["lon"], a["lat"], t["bbox"]) and not a["on_ground"]]
    n = len(inside)
    level = "critical" if n >= t["critical"] else "elevated" if n >= t["elevated"] else "normal"
    roles = _role_counts(inside)
    ops = []
    if roles.get("tanker", 0) >= 1:
        ops.append("aerial_refueling")
    if roles.get("aew", 0) >= 1:
        ops.append("airborne_early_warning")
    if roles.get("isr", 0) + roles.get("uav", 0) >= 2:
        ops.append("isr_coverage")
    if roles.get("fighter", 0) >= 4 and roles.get("tanker", 0) >= 1:
        ops.append("strike_package_indicators")
    if roles.get("bomber", 0):
        ops.append("bomber_presence")
    return {"theater": theater_id, "name": t["name"], "posture": level, "airborne_military_aircraft": n,
            "thresholds": {"elevated": t["elevated"], "critical": t["critical"]}, "by_role": roles,
            "indicators": ops}


@osint_tool(group="military", tier=1)
async def get_military_posture(theater: Optional[str] = None) -> str:
    """Military air posture for each theater (or one): airborne military aircraft seen on open ADS-B,
    a normal/elevated/critical level against fixed thresholds, a breakdown by role (tanker, AEW, ISR,
    fighter, bomber, transport) and indicators such as aerial refueling or strike-package patterns.

    Args:
        theater: Optional theater id: iran, levant, iraq, red-sea, arabian-peninsula, east-med, black-sea,
            baltic, taiwan, south-china-sea, korea, sahel, afghanistan-pakistan. Omit for all.
    """
    r = Result("get_military_posture")
    acs = await safe_fetch(r, "adsb.lol military feed", flights.ADSB_MIL_URL, flights.military_aircraft())
    if acs is None:
        return r.to_json()
    ids = [theater.lower()] if theater else list(geo.THEATERS)
    unknown = [i for i in ids if i not in geo.THEATERS]
    if unknown:
        return unavailable("get_military_posture", f"Unknown theater {unknown[0]!r}. Known: {', '.join(geo.THEATERS)}")
    rows = [_posture(i, geo.THEATERS[i], acs) for i in ids]
    await add_coverage(r, rows)
    r.data = {"theaters": rows, "global_military_aircraft_tracked": len(acs)}
    r.notes += [ADSB_NOTE, COVERAGE_NOTE,
                "Levels compare today's count with fixed starting thresholds (to be recalibrated from our own "
                "surge baselines); use get_military_surge for change over time."]
    return r.to_json()


COVERAGE_NOTE = ("'coverage' is the most aircraft (civil too) adsb.lol sees around any of three probe points in the theater; parts of a large theater can still be dark. When it is "
                 "'poor', open ADS-B cannot see this airspace and the posture is reported as 'unknown', not 'normal'.")


async def add_coverage(r: Result, rows: list[dict]) -> None:
    """Attach receiver coverage to each theater row; downgrade posture to 'unknown' where coverage is poor."""
    import asyncio

    async def one(row):
        t = geo.THEATERS[row["theater"]]
        w, s, e, n = t["bbox"]
        # Center plus two points along the diagonal: one point can fall in empty desert or sea.
        points = [((s + n) / 2, (w + e) / 2), (s + (n - s) * 0.25, w + (e - w) * 0.25), (s + (n - s) * 0.75, w + (e - w) * 0.75)]
        totals = []
        for lat, lon in points:
            try:
                totals.append((await flights.coverage_at(lat, lon))[0])
            except Exception:  # noqa: BLE001
                continue
        return row, (max(totals) if totals else None)

    results = await asyncio.gather(*(one(x) for x in rows))
    for row, total in results:
        if total is None:
            row["coverage"] = "unknown"
            continue
        row["aircraft_visible_at_probes"] = total
        row["coverage"] = "poor" if total < 10 else "partial" if total < 40 else "good"
        if row["coverage"] == "poor" and row["posture"] == "normal":
            row["posture"] = "unknown"
    r.source("adsb.lol coverage probe", flights.POINT_URL.split("{")[0], None,
             ok=any(t is not None for _, t in results))


@osint_tool(group="military", tier=1)
async def get_military_surge(theater: Optional[str] = None) -> str:
    """Change in military air activity: the current airborne count per theater compared with its own
    7-day average at the same collection points, flagging surges (well above baseline).

    Args:
        theater: Optional theater id (see get_military_posture). Omit for all theaters.
    """
    from osint import history

    r = Result("get_military_surge")
    acs = await safe_fetch(r, "adsb.lol military feed", flights.ADSB_MIL_URL, flights.military_aircraft())
    if acs is None:
        return r.to_json()
    ids = [theater.lower()] if theater else list(geo.THEATERS)
    rows = []
    try:
        for tid in ids:
            t = geo.THEATERS.get(tid)
            if not t:
                continue
            now_n = sum(1 for a in acs if geo.in_bbox(a["lon"], a["lat"], t["bbox"]) and not a["on_ground"])
            series = await history.military_series(tid, time.time() - 7 * 86400)
            base = [c for _, c in series]
            avg = sum(base) / len(base) if base else None
            ratio = (now_n / avg) if avg else None
            status = "insufficient_history"
            if avg is not None and len(base) >= 24:
                status = "surge" if (ratio or 0) >= 2 and now_n >= t["elevated"] else "above_normal" if (ratio or 0) >= 1.4 else \
                    "below_normal" if (ratio or 1) <= 0.6 else "normal"
            rows.append({"theater": tid, "name": t["name"], "current": now_n,
                         "baseline_7d_avg": round(avg, 1) if avg is not None else None,
                         "ratio": round(ratio, 2) if ratio else None, "samples": len(base), "status": status})
    except history.HistoryUnavailable as e:
        r.notes.append(str(e))
    r.data = {"theaters": rows}
    r.notes += [ADSB_NOTE, "Baselines are built by the 15-minute collector; a theater needs ~6 hours of samples first."]
    return r.to_json()


@osint_tool(group="military", tier=1)
async def get_airspace(country: str, include_civil_roles: bool = False) -> str:
    """Military aircraft currently over one country's territory on open ADS-B, with callsign, type,
    role, altitude, speed and position for each.

    Args:
        country: Country name or ISO code, e.g. "Iran", "IR", "Iraq".
        include_civil_roles: Also list military-registered transports/VIP jets (default only lists tactical roles first).
    """
    c = geo.country(country)
    if not c:
        return unavailable("get_airspace", f"Unknown country {country!r}")
    r = Result("get_airspace")
    acs = await safe_fetch(r, "adsb.lol military feed", flights.ADSB_MIL_URL, flights.military_aircraft())
    if acs is None:
        return r.to_json()
    inside = [a for a in acs if geo.in_country(a["lon"], a["lat"], c)]
    tactical = [a for a in inside if a["role"] in ("fighter", "bomber", "tanker", "aew", "isr", "uav", "helicopter")]
    listed = inside if include_civil_roles else tactical + [a for a in inside if a not in tactical]
    r.data = {"country": geo.country_brief(c), "military_aircraft": len(inside), "by_role": _role_counts(inside),
              "aircraft": listed[:80]}
    r.notes.append(ADSB_NOTE)
    return r.to_json()


@osint_tool(group="military", tier=2)
async def get_global_air_activity() -> str:
    """Worldwide snapshot of military aircraft on open ADS-B: totals by role, how many sit inside each
    tracked theater, and how many are outside all theaters."""
    r = Result("get_global_air_activity")
    acs = await safe_fetch(r, "adsb.lol military feed", flights.ADSB_MIL_URL, flights.military_aircraft())
    if acs is None:
        return r.to_json()
    airborne = [a for a in acs if not a["on_ground"]]
    per = {tid: sum(1 for a in airborne if geo.in_bbox(a["lon"], a["lat"], t["bbox"])) for tid, t in geo.THEATERS.items()}
    in_any = sum(1 for a in airborne if any(geo.in_bbox(a["lon"], a["lat"], t["bbox"]) for t in geo.THEATERS.values()))
    emergencies = [a for a in acs if a.get("emergency") or a.get("squawk") in ("7500", "7600", "7700")]
    r.data = {"total": len(acs), "airborne": len(airborne), "by_role": _role_counts(airborne), "by_theater": per,
              "outside_theaters": len(airborne) - in_any, "emergency_squawks": emergencies[:10]}
    r.notes.append(ADSB_NOTE)
    return r.to_json()


@osint_tool(group="military", tier=1, requires=("AISSTREAM_API_KEY",))
async def get_maritime_activity(region: str, listen_seconds: int = 20) -> str:
    """Ships broadcasting AIS in a region right now: counts by category (military, law enforcement,
    tanker, cargo, passenger...) and the list of military and law-enforcement vessels.

    Args:
        region: A theater id (e.g. iran, red-sea), a country name/ISO code, or a "west,south,east,north" box.
        listen_seconds: How long to listen to the live AIS stream (5-45, default 20).
    """
    bbox, label = geo.region_bbox(region)
    if not bbox:
        return unavailable("get_maritime_activity", f"Could not resolve region {region!r}")
    r = Result("get_maritime_activity")
    vessels = await safe_fetch(r, "aisstream.io", world.AISSTREAM_URL, world.ais_snapshot(bbox, listen_seconds))
    if vessels is None:
        return r.to_json()
    cats = Counter(v["category"] for v in vessels)
    r.data = {"region": label, "bbox": bbox, "vessels_seen": len(vessels), "by_category": dict(cats.most_common()),
              "military_and_law_enforcement": [v for v in vessels if v["category"] in ("military", "law_enforcement")][:50],
              "tankers": [v for v in vessels if v["category"] == "tanker"][:30]}
    r.notes += ["AIS is self-reported and often switched off by warships and sanctioned tankers; absence is not evidence.",
                "Static data (type, name) arrives every few minutes, so short listens leave many vessels 'unknown'."]
    return r.to_json()


@osint_tool(group="military", tier=1)
async def get_chokepoint_status(chokepoint: Optional[str] = None) -> str:
    """Daily ship transits through strategic maritime chokepoints (Hormuz, Bab el-Mandeb, Suez, Malacca,
    Panama, Bosporus, Gibraltar, Taiwan Strait...): latest week vs the previous 4 weeks, by vessel type.

    Args:
        chokepoint: Optional id: hormuz, bab_el_mandeb, suez, malacca, panama, bosporus, gibraltar,
            taiwan_strait, dover, cape_of_good_hope. Omit for all.
    """
    import asyncio

    ids = [chokepoint.lower()] if chokepoint else list(geo.CHOKEPOINTS)
    if any(i not in geo.CHOKEPOINTS for i in ids):
        return unavailable("get_chokepoint_status", f"Unknown chokepoint. Known: {', '.join(geo.CHOKEPOINTS)}")
    r = Result("get_chokepoint_status")

    async def one(cid):
        cp = geo.CHOKEPOINTS[cid]
        rows = await safe_fetch(r, f"IMF PortWatch ({cp['name']})", world.PORTWATCH_URL,
                                world.chokepoint_transits(cp["portwatch"], days=400))
        if not rows:
            return {"chokepoint": cid, "name": cp["name"], "status": "no_data"}
        rows = sorted(rows, key=lambda x: x.get("date") or "", reverse=True)
        last7, prev28 = rows[:7], rows[7:35]
        year_ago = rows[365:372]
        avg = lambda xs, k: round(sum(x.get(k) or 0 for x in xs) / len(xs), 1) if xs else None  # noqa: E731
        pct = lambda a, b: round((a - b) / b * 100, 1) if a is not None and b else None  # noqa: E731
        cur, base, yoy = avg(last7, "n_total"), avg(prev28, "n_total"), avg(year_ago, "n_total")
        change, change_yoy = pct(cur, base), pct(cur, yoy)
        # Judge against a year ago when available: a disruption lasting weeks hides in a 28-day baseline.
        ref = change_yoy if change_yoy is not None else change
        status = "normal"
        if ref is not None:
            status = "severe_disruption" if ref <= -50 else "disrupted" if ref <= -25 else \
                "elevated_traffic" if ref >= 25 else "normal"
        return {"chokepoint": cid, "name": cp["name"], "latest_date": rows[0].get("date"),
                "avg_daily_transits_last_7d": cur, "avg_daily_transits_prior_28d": base, "change_vs_prior_28d_pct": change,
                "avg_daily_transits_same_week_last_year": yoy, "change_vs_last_year_pct": change_yoy,
                "tankers_last_7d_avg": avg(last7, "n_tanker"), "tankers_same_week_last_year": avg(year_ago, "n_tanker"),
                "status": status, "status_basis": "vs_last_year" if change_yoy is not None else "vs_prior_28d"}

    r.data = {"chokepoints": list(await asyncio.gather(*(one(i) for i in ids)))}
    r.notes.append("PortWatch counts come from AIS and are published with a few days' lag.")
    return r.to_json()
