"""Everything else: advisories, internet outages, chokepoints, humanitarian and
health data, defense indicators, social media, webcams, energy, ships, NO2."""

from __future__ import annotations

import asyncio
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date

from app.settings import settings
from osint.core import SourceError, cached, get_json, get_text, http, iso

STATE_DEPT_URL = "https://cadataapi.state.gov/api/TravelAdvisories"
IODA_EVENTS_URL = "https://api.ioda.inetintel.cc.gatech.edu/v2/outages/events"
PORTWATCH_URL = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/Daily_Chokepoints_Data/FeatureServer/0/query"
UNHCR_POP_URL = "https://api.unhcr.org/population/v1/population/"
UNHCR_ASYLUM_URL = "https://api.unhcr.org/population/v1/asylum-applications/"
WHO_DON_URL = "https://www.who.int/api/news/diseaseoutbreaknews"
WORLDBANK_URL = "https://api.worldbank.org/v2/country/{iso}/indicator/{ind}"
POLYMARKET_URL = "https://gamma-api.polymarket.com/public-search"
BLUESKY_URL = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"
REDDIT_URL = "https://oauth.reddit.com/r/{sub}/{sort}"
REDDIT_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_UA = "server:soldieriq.osint:v1.0"
FAA_URL = "https://nasstatus.faa.gov/api/airport-status-information"
CABLE_COUNTRY_URL = "https://www.submarinecablemap.com/api/v3/country/{slug}.json"
WINDY_URL = "https://api.windy.com/webcams/api/v3/webcams"
EIA_URL = "https://api.eia.gov/v2/{route}/data/"
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CDSE_STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"


# ── Travel advisories (US State Department) ──────────────────────────────────

async def state_dept_advisories() -> tuple[dict[str, dict], str]:
    async def fetch():
        data = await get_json(STATE_DEPT_URL, timeout=40)
        out: dict[str, dict] = {}
        for a in data or []:
            m = re.search(r"Level (\d)", a.get("Title") or "")
            level = int(m.group(1)) if m else None
            summary = re.sub(r"<[^>]+>", " ", a.get("Summary") or "")
            summary = re.sub(r"\s+", " ", summary).strip()
            for code in a.get("Category") or []:
                out[code.upper()] = {
                    "title": a.get("Title"), "level": level,
                    "level_label": {1: "Exercise normal precautions", 2: "Exercise increased caution",
                                    3: "Reconsider travel", 4: "Do not travel"}.get(level),
                    "summary": summary[:600], "updated": a.get("Updated"), "url": a.get("Link"),
                }
        return out

    return await cached("advisories:us", 6 * 3600, fetch)


# ── Internet outages (IODA, Georgia Tech) ────────────────────────────────────

async def ioda_outages(country_iso2: str | None = None, days: int = 3) -> tuple[list[dict], str]:
    until = int(time.time())
    since = until - max(1, min(days, 14)) * 86400

    async def fetch():
        params = {"from": since, "until": until, "limit": 200, "entityType": "country"}
        if country_iso2:
            params["entityCode"] = country_iso2.upper()
        data = await get_json(IODA_EVENTS_URL, params=params, timeout=45)
        out = []
        for e in data.get("data") or []:
            out.append({
                "entity": e.get("location"), "name": e.get("location_name"),
                "start": iso(e["start"]) if e.get("start") else None,
                "duration_hours": round((e.get("duration") or 0) / 3600, 1),
                "datasource": {"bgp": "BGP routing", "ping-slash24": "active probing", "gtr": "Google traffic",
                               "merit-nt": "network telescope"}.get(e.get("datasource"), e.get("datasource")),
                "score": round(e.get("score") or 0),
            })
        out.sort(key=lambda x: x["score"], reverse=True)
        return out

    return await cached(f"ioda:{country_iso2 or 'all'}:{days}:{until // 900}", 900, fetch)


# ── Chokepoint transits (IMF PortWatch) ──────────────────────────────────────

async def chokepoint_transits(portwatch_name: str, days: int = 60) -> tuple[list[dict], str]:
    async def fetch():
        where = f"portname='{portwatch_name.replace(chr(39), '')}'"
        data = await get_json(PORTWATCH_URL, params={
            "where": where, "outFields": "date,n_total,n_tanker,n_container,n_dry_bulk,n_cargo,capacity",
            "orderByFields": "date DESC", "resultRecordCount": days, "f": "json",
        }, timeout=40)
        return [f["attributes"] for f in data.get("features") or []]

    return await cached(f"portwatch:{portwatch_name}:{days}", 6 * 3600, fetch)


# ── Humanitarian / health ────────────────────────────────────────────────────

async def unhcr_population(iso3: str, role: str = "origin") -> tuple[list[dict], str]:
    """Refugees/asylum seekers/IDPs from (origin) or hosted in (asylum) a country, by year."""
    key = "coo" if role == "origin" else "coa"

    async def fetch():
        data = await get_json(UNHCR_POP_URL, params={key: iso3, "yearFrom": date.today().year - 6, "limit": 100,
                                                     ("coo_all" if role == "asylum" else "coa_all"): "false"}, timeout=40)
        return data.get("items") or []

    return await cached(f"unhcr:pop:{role}:{iso3}", 24 * 3600, fetch)


async def unhcr_asylum_applications(iso3: str) -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(UNHCR_ASYLUM_URL, params={"coo": iso3, "yearFrom": date.today().year - 4,
                                                        "limit": 200, "coa_all": "true"}, timeout=40)
        return data.get("items") or []

    return await cached(f"unhcr:asylum:{iso3}", 24 * 3600, fetch)


async def who_outbreaks(top: int = 30) -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(WHO_DON_URL, params={"$top": top, "$orderby": "PublicationDateAndTime desc"}, timeout=40)
        out = []
        for d in data.get("value") or []:
            summary = re.sub(r"<[^>]+>", " ", d.get("Summary") or "")
            out.append({
                "title": d.get("OverrideTitle") or d.get("Title"),
                "published": d.get("PublicationDateAndTime") or d.get("PublicationDate"),
                "summary": re.sub(r"\s+", " ", summary).strip()[:500],
                "url": f"https://www.who.int/emergencies/disease-outbreak-news/item/{d.get('UrlName')}",
            })
        return out

    return await cached(f"who:don:{top}", 6 * 3600, fetch)


async def worldbank_indicator(iso3: str, indicator: str, years: int = 10) -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(WORLDBANK_URL.format(iso=iso3, ind=indicator),
                              params={"format": "json", "per_page": years, "mrv": years}, timeout=40)
        if not isinstance(data, list) or len(data) < 2:
            return []
        return [{"year": r.get("date"), "value": r.get("value")} for r in data[1] or [] if r.get("value") is not None]

    return await cached(f"wb:{iso3}:{indicator}:{years}", 7 * 24 * 3600, fetch)


# ── Prediction markets (Polymarket) ──────────────────────────────────────────

async def polymarket_search(query: str, limit: int = 10) -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(POLYMARKET_URL, params={"q": query, "limit_per_type": limit, "events_status": "active"},
                              timeout=30)
        out = []
        for ev in (data.get("events") or [])[:limit]:
            markets = []
            today = date.today().isoformat()
            for m in ev.get("markets") or []:
                if m.get("closed") or (m.get("endDate") or "9999")[:10] < today:
                    continue
                try:
                    outcomes = json.loads(m.get("outcomes") or "[]")
                    prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
                except (ValueError, TypeError):
                    outcomes, prices = [], []
                markets.append({"question": m.get("question"), "outcomes": dict(zip(outcomes, prices)),
                                "volume_usd": m.get("volumeNum") or m.get("volume"), "end_date": m.get("endDate")})
            out.append({"event": ev.get("title"), "slug": ev.get("slug"), "end_date": ev.get("endDate"),
                        "volume_usd": ev.get("volume"), "url": f"https://polymarket.com/event/{ev.get('slug')}",
                        "markets": markets[:6]})
        return out

    return await cached(f"polymarket:{query.lower()}:{limit}", 900, fetch)


# ── Social ──────────────────────────────────────────────────────────────────

async def bluesky_search(query: str, limit: int = 25) -> tuple[list[dict], str]:
    async def fetch():
        data = await get_json(BLUESKY_URL, params={"q": query, "limit": max(1, min(limit, 100)), "sort": "latest"},
                              timeout=30)
        out = []
        for p in data.get("posts") or []:
            author = p.get("author") or {}
            rec = p.get("record") or {}
            post_id = (p.get("uri") or "").rsplit("/", 1)[-1]
            out.append({
                "author": author.get("handle"), "display_name": author.get("displayName"),
                "text": (rec.get("text") or "")[:500], "created_at": rec.get("createdAt"),
                "likes": p.get("likeCount"), "reposts": p.get("repostCount"), "replies": p.get("replyCount"),
                "url": f"https://bsky.app/profile/{author.get('handle')}/post/{post_id}",
            })
        return out

    return await cached(f"bsky:{query.lower()}:{limit}", 600, fetch)


async def _reddit_token() -> str:
    """Application-only OAuth token for Reddit's official API."""

    async def fetch():
        resp = await http().post(REDDIT_TOKEN_URL, data={"grant_type": "client_credentials"},
                                 auth=(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET),
                                 headers={"User-Agent": REDDIT_UA}, timeout=30)
        if resp.status_code >= 400:
            raise SourceError(f"Reddit token request returned HTTP {resp.status_code}")
        return resp.json().get("access_token")

    token, _ = await cached("reddit:token", 50 * 60, fetch)
    if not token:
        raise SourceError("Reddit returned no access token")
    return token


async def reddit_posts(sub: str, sort: str = "hot", limit: int = 50) -> tuple[list[dict], str]:
    if not (settings.REDDIT_CLIENT_ID and settings.REDDIT_CLIENT_SECRET):
        raise SourceError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not configured")
    if not re.fullmatch(r"[A-Za-z0-9_]{2,40}", sub) or sort not in ("hot", "new", "rising", "top"):
        raise SourceError("invalid subreddit or sort")

    async def fetch():
        token = await _reddit_token()
        data = await get_json(REDDIT_URL.format(sub=sub, sort=sort), params={"limit": limit, "raw_json": 1},
                              headers={"Authorization": f"Bearer {token}", "User-Agent": REDDIT_UA}, timeout=30)
        now = time.time()
        out = []
        for c in (data.get("data") or {}).get("children") or []:
            d = c.get("data") or {}
            age_h = max(0.25, (now - (d.get("created_utc") or now)) / 3600)
            score = d.get("score") or 0
            out.append({
                "title": d.get("title"), "subreddit": d.get("subreddit"), "score": score,
                "comments": d.get("num_comments"), "age_hours": round(age_h, 1),
                "velocity": round(score / age_h, 1), "domain": d.get("domain"),
                "url": d.get("url_overridden_by_dest") or d.get("url"),
                "permalink": f"https://www.reddit.com{d.get('permalink')}",
            })
        return out

    return await cached(f"reddit:{sub}:{sort}:{limit}", 900, fetch)


# ── Aviation (FAA) ───────────────────────────────────────────────────────────

async def faa_airport_status() -> tuple[list[dict], str]:
    async def fetch():
        text = await get_text(FAA_URL, timeout=30)
        root = ET.fromstring(text.encode("utf-8"))
        out = []
        for dt in root.iter("Delay_type"):
            kind = (dt.findtext("Name") or "").strip()
            for ap in dt.iter("Airport"):
                out.append({"kind": kind, "airport": ap.findtext("ARPT"), "reason": (ap.findtext("Reason") or "")[:200],
                            "start": ap.findtext("Start"), "reopen": ap.findtext("Reopen")})
            for prog in dt.iter("Program"):
                out.append({"kind": kind, "airport": prog.findtext("ARPT"), "reason": prog.findtext("Reason"),
                            "average_delay": prog.findtext("Avg"), "max_delay": prog.findtext("Max")})
            for d in dt.iter("Delay"):
                out.append({"kind": kind, "airport": d.findtext("ARPT"), "reason": d.findtext("Reason"),
                            "min_delay": d.findtext("Arrival_Departure/Min"), "max_delay": d.findtext("Arrival_Departure/Max")})
        return out

    return await cached("faa:status", 300, fetch)


# ── Submarine cables (TeleGeography) ─────────────────────────────────────────

async def cables_for_country(country_name: str) -> tuple[dict, str]:
    slug = re.sub(r"[^a-z0-9]+", "-", country_name.lower()).strip("-")

    async def fetch():
        return await get_json(CABLE_COUNTRY_URL.format(slug=slug), timeout=30)

    return await cached(f"cables:{slug}", 7 * 24 * 3600, fetch)


# ── Webcams (Windy) ──────────────────────────────────────────────────────────

async def windy_webcams(bbox: tuple[float, float, float, float], limit: int = 25) -> tuple[list[dict], str]:
    if not settings.WINDY_API_KEY:
        raise SourceError("WINDY_API_KEY not configured")
    w, s, e, n = bbox

    async def fetch():
        data = await get_json(WINDY_URL, params={"bbox": f"{n},{e},{s},{w}", "limit": max(1, min(limit, 50)),
                                                 "include": "location,images,player,urls"},
                              headers={"x-windy-api-key": settings.WINDY_API_KEY}, timeout=30)
        out = []
        for c in data.get("webcams") or []:
            loc = c.get("location") or {}
            images = (c.get("images") or {}).get("current") or {}
            out.append({
                "webcam_id": c.get("webcamId"), "title": c.get("title"), "status": c.get("status"),
                "last_updated": c.get("lastUpdatedOn"), "city": loc.get("city"), "country": loc.get("country"),
                "lat": loc.get("latitude"), "lon": loc.get("longitude"), "image_url": images.get("preview"),
                "player_url": ((c.get("player") or {}).get("day")), "page_url": (c.get("urls") or {}).get("detail"),
            })
        return out

    return await cached(f"windy:{bbox}:{limit}", 600, fetch)


async def windy_webcam(webcam_id: str) -> tuple[dict, str]:
    if not settings.WINDY_API_KEY:
        raise SourceError("WINDY_API_KEY not configured")
    if not re.fullmatch(r"\d{4,15}", webcam_id):
        raise SourceError("invalid webcam id")

    async def fetch():
        return await get_json(f"{WINDY_URL}/{webcam_id}", params={"include": "location,images,player,urls"},
                              headers={"x-windy-api-key": settings.WINDY_API_KEY}, timeout=30)

    return await cached(f"windy:cam:{webcam_id}", 300, fetch)


# ── Energy (EIA) ─────────────────────────────────────────────────────────────

EIA_SERIES = {
    "brent_spot_usd_bbl": ("petroleum/pri/spt", "RBRTE", "daily"),
    "wti_spot_usd_bbl": ("petroleum/pri/spt", "RWTC", "daily"),
    "us_crude_stocks_kbbl": ("petroleum/stoc/wstk", "WCESTUS1", "weekly"),
    "us_gasoline_stocks_kbbl": ("petroleum/stoc/wstk", "WGTSTUS1", "weekly"),
    "henry_hub_gas_usd_mmbtu": ("natural-gas/pri/fut", "RNGC1", "daily"),
}


async def eia_series(name: str, points: int = 10) -> tuple[list[dict], str]:
    if not settings.EIA_API_KEY:
        raise SourceError("EIA_API_KEY not configured")
    route, series, freq = EIA_SERIES[name]

    async def fetch():
        params = [("api_key", settings.EIA_API_KEY), ("frequency", freq), ("data[0]", "value"),
                  ("facets[series][]", series), ("sort[0][column]", "period"), ("sort[0][direction]", "desc"),
                  ("length", str(points))]
        resp = await http().get(EIA_URL.format(route=route), params=params, timeout=40)
        if resp.status_code >= 400:
            raise SourceError(f"EIA returned HTTP {resp.status_code}")
        rows = (resp.json().get("response") or {}).get("data") or []
        return [{"period": r.get("period"), "value": r.get("value"), "units": r.get("units")} for r in rows]

    return await cached(f"eia:{name}:{points}", 6 * 3600, fetch)


# ── Ships (aisstream.io) ─────────────────────────────────────────────────────

AIS_SHIP_TYPES = {35: "military", 55: "law_enforcement", 51: "search_and_rescue", 30: "fishing", 52: "tug"}


def ais_category(code) -> str:
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "unknown"
    if c in AIS_SHIP_TYPES:
        return AIS_SHIP_TYPES[c]
    if 60 <= c <= 69:
        return "passenger"
    if 70 <= c <= 79:
        return "cargo"
    if 80 <= c <= 89:
        return "tanker"
    return "other"


async def ais_snapshot(bbox: tuple[float, float, float, float], seconds: int = 20) -> tuple[list[dict], str]:
    """Listen to the AIS stream for `seconds` and return the vessels seen in the box."""
    if not settings.AISSTREAM_API_KEY:
        raise SourceError("AISSTREAM_API_KEY not configured")
    w, s, e, n = bbox

    async def fetch():
        import websockets

        vessels: dict[str, dict] = {}
        sub = {"APIKey": settings.AISSTREAM_API_KEY, "BoundingBoxes": [[[s, w], [n, e]]],
               "FilterMessageTypes": ["PositionReport", "ShipStaticData", "StandardClassBPositionReport"]}
        deadline = time.monotonic() + max(5, min(seconds, 45))
        try:
            async with websockets.connect(AISSTREAM_URL, open_timeout=15, max_size=2**20) as ws:
                await ws.send(json.dumps(sub))
                while time.monotonic() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(0.5, deadline - time.monotonic()))
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(raw)
                    meta = msg.get("MetaData") or {}
                    mmsi = str(meta.get("MMSI") or "")
                    if not mmsi:
                        continue
                    v = vessels.setdefault(mmsi, {"mmsi": mmsi})
                    v["name"] = (meta.get("ShipName") or v.get("name") or "").strip() or None
                    v["lat"], v["lon"] = meta.get("latitude"), meta.get("longitude")
                    v["time"] = meta.get("time_utc")
                    body = (msg.get("Message") or {}).get(msg.get("MessageType")) or {}
                    if msg.get("MessageType") == "ShipStaticData":
                        v["ship_type"] = body.get("Type")
                        v["category"] = ais_category(body.get("Type"))
                        v["destination"] = (body.get("Destination") or "").strip() or None
                        v["call_sign"] = (body.get("CallSign") or "").strip() or None
                    else:
                        v["speed_kt"] = body.get("Sog")
                        v["heading"] = body.get("TrueHeading")
        except (OSError, websockets.exceptions.WebSocketException) as e:  # type: ignore[attr-defined]
            raise SourceError(f"AIS stream error: {type(e).__name__}") from e
        for v in vessels.values():
            v.setdefault("category", "unknown")
        return list(vessels.values())

    return await cached(f"ais:{bbox}", 300, fetch)


# ── NO2 (Copernicus Sentinel-5P) ─────────────────────────────────────────────

_NO2_EVALSCRIPT = """//VERSION=3
function setup(){return{input:[{bands:["NO2","dataMask"]}],output:[{id:"no2",bands:1,sampleType:"FLOAT32"},{id:"dataMask",bands:1}]};}
function evaluatePixel(s){return{no2:[s.NO2],dataMask:[s.dataMask]};}"""


async def _cdse_token() -> str:
    async def fetch():
        resp = await http().post(CDSE_TOKEN_URL, data={
            "grant_type": "client_credentials", "client_id": settings.COPERNICUS_CLIENT_ID,
            "client_secret": settings.COPERNICUS_CLIENT_SECRET}, timeout=30)
        if resp.status_code >= 400:
            raise SourceError(f"Copernicus token request returned HTTP {resp.status_code}")
        return resp.json().get("access_token")

    token, _ = await cached("cdse:token", 50 * 60, fetch)
    return token


async def no2_mean(bbox: tuple[float, float, float, float], start: date, end: date) -> tuple[dict, str]:
    """Mean tropospheric NO2 column (mol/m2) over a bbox and period."""
    if not (settings.COPERNICUS_CLIENT_ID and settings.COPERNICUS_CLIENT_SECRET):
        raise SourceError("COPERNICUS_CLIENT_ID / COPERNICUS_CLIENT_SECRET not configured")

    async def fetch():
        token = await _cdse_token()
        body = {
            "input": {"bounds": {"bbox": list(bbox), "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                      "data": [{"type": "sentinel-5p-l2", "dataFilter": {"timeRange": {
                          "from": f"{start.isoformat()}T00:00:00Z", "to": f"{end.isoformat()}T23:59:59Z"}}}]},
            "aggregation": {"timeRange": {"from": f"{start.isoformat()}T00:00:00Z", "to": f"{end.isoformat()}T23:59:59Z"},
                            "aggregationInterval": {"of": f"P{max(1, (end - start).days)}D"},
                            "evalscript": _NO2_EVALSCRIPT, "resx": 0.1, "resy": 0.1},
        }
        resp = await http().post(CDSE_STATS_URL, json=body, headers={"Authorization": f"Bearer {token}"}, timeout=90)
        if resp.status_code >= 400:
            raise SourceError(f"Copernicus statistics returned HTTP {resp.status_code}")
        intervals = resp.json().get("data") or []
        if not intervals:
            return {"mean": None}
        stats = ((intervals[0].get("outputs") or {}).get("no2") or {}).get("bands", {}).get("B0", {}).get("stats", {})
        return {"mean": stats.get("mean"), "sample_count": stats.get("sampleCount"), "no_data": stats.get("noDataCount")}

    return await cached(f"no2:{bbox}:{start}:{end}", 24 * 3600, fetch)
