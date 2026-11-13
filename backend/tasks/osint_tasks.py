"""OSINT collector (Celery beat). Builds the history the OSINT tools need:

- every 15 min (osint.collect): military-aircraft counts per theater (surge
  baselines), GDELT conflict-event counts per country per hour (anomalies),
  and notable events (strike reports, widely reported stories, high-signal
  GDELT events, elevated air posture) into the event timeline;
- daily (osint.daily_risk): each active country's risk index (country history).

Needs a beat process: `celery -A app.worker beat`. Without it the live tools
still work; only the history-based tools stay empty.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import Counter
from datetime import date, datetime, timezone

from app.logger import logger
from app.worker import celery_app


def _ts(s: str | None) -> float:
    if not s:
        return time.time()
    for fmt in ("%Y%m%d%H%M%S",):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


async def _collect() -> dict:
    from osint import geo, history
    from osint.core import Result, reset_clients
    from osint.signals import FIPS_ISO2, headlines, strikes
    from osint.sources import flights, gdelt, news
    from osint.tools.military import _posture

    reset_clients()
    r = Result("collector")
    stats: dict = {}

    # 1. Military aircraft per theater.
    try:
        acs, _ = await flights.military_aircraft()
        now = time.time()
        airborne = [a for a in acs if not a["on_ground"]]
        events = []
        for tid, t in geo.THEATERS.items():
            p = _posture(tid, t, airborne)
            await history.record_military(tid, p["airborne_military_aircraft"], now)
            if p["posture"] != "normal":
                events.append({"id": f"mil:{tid}:{int(now // 3600)}", "ts": now, "domain": "military",
                               "title": f"{t['name']}: {p['posture']} military air posture "
                                        f"({p['airborne_military_aircraft']} aircraft; {', '.join(p['indicators']) or 'no indicators'})",
                               "theater": tid, "source": "adsb.lol"})
        stats["military_events"] = await history.add_events(events)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[osint] collector: aircraft failed: {e}")

    # 2. GDELT conflict counts per country-hour + high-signal events.
    try:
        evs, _ = await gdelt.recent_events(1)
        conflict = [e for e in evs if e["root_code"] in gdelt.CONFLICT_ROOTS]
        counts = Counter(FIPS_ISO2.get(e["country_fips"], e["country_fips"]) for e in conflict if e["country_fips"])
        await history.bump_counts(dict(counts), int(time.time() // 3600))
        notable = [e for e in conflict if e["precision"] in ("world_city", "city", "us_state")
                   and (e["num_sources"] >= 2 or e["num_articles"] >= 5 or e["root_code"] == "20")]
        stats["gdelt_events"] = await history.add_events({
            "id": e["id"], "ts": _ts(e["date_added"]), "domain": "conflict",
            "title": f"{e['category'].replace('_', ' ')}: {e.get('actor1') or '?'} vs {e.get('actor2') or '?'} at {e['place']}",
            "place": e["place"], "country": FIPS_ISO2.get(e["country_fips"], e["country_fips"]),
            "lat": e["lat"], "lon": e["lon"], "url": e["source_url"], "source": "GDELT",
            "num_sources": e["num_sources"]} for e in notable)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[osint] collector: gdelt failed: {e}")

    # 3. Telegram strike reports.
    try:
        reports = await strikes(r, hours=3)
        stats["strike_events"] = await history.add_events({
            "id": "tg:" + s["url"], "ts": _ts(s["time"]), "domain": "strike",
            "title": f"{s['kind']} at {s['place']} ({s['severity']}, {s['verdict']}): {s['text'][:200]}",
            "place": s["place"], "country": s["country"], "lat": s["lat"], "lon": s["lon"], "url": s["url"],
            "source": f"t.me/{s['channel']}", "verdict": s["verdict"]} for s in reports)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[osint] collector: telegram failed: {e}")

    # 4. Widely reported stories.
    try:
        items = await headlines(r, hours=3)
        clusters = [c for c in news.cluster_headlines(items)
                    if c["outlet_count"] >= 3 or (c["outlet_count"] >= 2 and (c["best_tier"] or 9) <= 2)]
        evs = []
        for c in clusters:
            ctry = next((cc for cc in geo.all_countries() if len(cc["name"]) > 3 and cc["name"].lower() in c["headline"].lower()), None)
            evs.append({"id": "news:" + hashlib.sha1(c["headline"].lower().encode()).hexdigest()[:16],
                        "ts": _ts(c["first_seen"]), "domain": "news", "title": c["headline"],
                        "country": ctry["iso2"] if ctry else None, "url": c["url"],
                        "source": ", ".join(c["outlets"][:5]), "outlets": c["outlet_count"]})
        stats["news_events"] = await history.add_events(evs)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[osint] collector: news failed: {e}")
    return stats


async def _daily_risk() -> dict:
    from osint import geo, history, signals
    from osint.core import Result, reset_clients
    from osint.tools.country import compute_risk

    reset_clients()
    r = Result("daily_risk")
    s = await signals.gather(r, gdelt_hours=24, strike_hours=24, news_hours=24, want=("gdelt", "strikes", "news"))
    active = Counter(signals.FIPS_ISO2.get(e["country_fips"], e["country_fips"]) for e in s["gdelt"])
    for x in s["strikes"]:
        active[x["country"]] += 5
    hotspot_countries = {cc for h in geo.HOTSPOTS.values() for cc in h["countries"]}
    targets = {cc for cc, _ in active.most_common(40)} | hotspot_countries
    day = date.today().isoformat()
    done = 0
    for iso2 in sorted(targets):
        c = geo.country(iso2)
        if not c:
            continue
        risk = await compute_risk(r, c, s)
        await history.record_risk(iso2, day, {"risk_index": risk["risk_index"], "band": risk["band"],
                                               "components": risk["components"]})
        done += 1
    return {"countries": done}


@celery_app.task(name="osint.collect", time_limit=600, soft_time_limit=540)
def collect() -> dict:
    result = asyncio.run(_collect())
    logger.info(f"[osint] collect: {result}")
    return result


@celery_app.task(name="osint.daily_risk", time_limit=1200, soft_time_limit=1100)
def daily_risk() -> dict:
    result = asyncio.run(_daily_risk())
    logger.info(f"[osint] daily_risk: {result}")
    return result
