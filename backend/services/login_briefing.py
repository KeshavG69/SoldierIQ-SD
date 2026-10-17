"""
Login briefing — the chat agent speaks first when the user signs in.

It looks at three things and writes a short, situational opener:
  1. The user's saved document selection: what those documents cover, plus
     documents that are new or changed since the user's last briefing.
  2. Where the user is: browser coordinates when they allowed location,
     otherwise a rough guess from their IP. Reverse-geocoded to a place name,
     with current weather (Open-Meteo, no API key).
  3. Their local time and day: morning briefing vs. end-of-day wrap-up.

Every source is best-effort: a failed lookup just drops that part of the
context, and if the LLM call fails we fall back to a plain template.
"""

import asyncio
import ipaddress
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

from clients import document_selection
from clients.postgres_client import get_postgres_client
from clients.ultimate_llm import get_llm
from app.logger import logger

BRIEFING_MODEL = "google/gemini-3-flash-preview"
MAX_DOCS = 12            # selected documents described to the model
SNIPPET_CHARS = 1200     # per-document content excerpt
MAX_NEW_DOCS = 6         # "new since last visit" items
HTTP_TIMEOUT = 4.0

# WMO weather codes (Open-Meteo `weather_code`) → words.
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow",
    73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 85: "snow showers",
    86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


# ---------------------------------------------------------------- time of day
def _local_time(tz_name: Optional[str], fallback_tz: Optional[str]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    for name in (tz_name, fallback_tz):
        if not name:
            continue
        try:
            now = now.astimezone(ZoneInfo(name))
            break
        except Exception:
            continue
    h = now.hour
    if 5 <= h < 12:
        part = "morning"
    elif 12 <= h < 17:
        part = "afternoon"
    elif 17 <= h < 22:
        part = "evening"
    else:
        part = "night"
    return {
        "local_time": now.strftime("%A %d %B %Y, %H:%M"),
        "timezone": str(now.tzinfo),
        "part_of_day": part,
        "is_weekend": now.weekday() >= 5,
    }


# ------------------------------------------------------------------ location
def _public_ip(ip: Optional[str]) -> Optional[str]:
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    return None if (addr.is_private or addr.is_loopback or addr.is_reserved) else str(addr)


async def _locate(
    client: httpx.AsyncClient,
    lat: Optional[float],
    lon: Optional[float],
    client_ip: Optional[str],
) -> Optional[Dict[str, Any]]:
    """Place name + coordinates, from the browser's position or the IP."""
    if lat is not None and lon is not None:
        # ~1 km precision is plenty for a place name and weather, and avoids
        # sending the user's exact position to third-party services.
        lat, lon = round(lat, 2), round(lon, 2)
        loc: Dict[str, Any] = {"latitude": lat, "longitude": lon, "source": "device"}
        try:
            # OpenStreetMap Nominatim (usage policy: identify the app, low volume).
            r = await client.get(
                "https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 10},
                headers={"User-Agent": "SoldierIQ/1.0 (login briefing)"},
            )
            a = r.json().get("address") or {}
            loc.update({
                "city": a.get("city") or a.get("town") or a.get("village") or a.get("county"),
                "region": a.get("state"),
                "country": a.get("country"),
            })
        except Exception as e:
            logger.info(f"[briefing] reverse geocode failed: {e}")
        return loc

    ip = _public_ip(client_ip)
    if not ip:
        return None
    try:
        r = await client.get(f"https://ipwho.is/{ip}")
        d = r.json()
        if not d.get("success"):
            return None
        return {
            "latitude": d.get("latitude"),
            "longitude": d.get("longitude"),
            "city": d.get("city"),
            "region": d.get("region"),
            "country": d.get("country"),
            "timezone": (d.get("timezone") or {}).get("id"),
            "source": "ip (approximate)",
        }
    except Exception as e:
        logger.info(f"[briefing] IP geolocation failed: {e}")
        return None


async def _weather(client: httpx.AsyncClient, lat: float, lon: float) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m,precipitation",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                "forecast_days": 1,
                "timezone": "auto",
            },
        )
        d = r.json()
        cur, day = d.get("current") or {}, d.get("daily") or {}

        def first(key):
            v = day.get(key)
            return v[0] if isinstance(v, list) and v else None

        return {
            "now": _WMO.get(cur.get("weather_code"), "unknown"),
            "temperature_c": cur.get("temperature_2m"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "today": _WMO.get(first("weather_code"), "unknown"),
            "high_c": first("temperature_2m_max"),
            "low_c": first("temperature_2m_min"),
            "precipitation_chance_pct": first("precipitation_probability_max"),
        }
    except Exception as e:
        logger.info(f"[briefing] weather lookup failed: {e}")
        return None


# ----------------------------------------------------------------- documents
def _doc_row(r) -> Dict[str, Any]:
    return {
        "name": r["filename"],
        "folder": r["folder_name"],
        "status": r["status"],
        "added": r["created_at"].isoformat() if r["created_at"] else None,
    }


async def _documents(
    organization_id: str, document_ids: List[str], since: Optional[datetime]
) -> Dict[str, Any]:
    pool = await get_postgres_client().get_pool()
    org = uuid.UUID(organization_id)
    ids = []
    for i in document_ids[:MAX_DOCS]:
        try:
            ids.append(uuid.UUID(i))
        except ValueError:
            pass

    async with pool.acquire() as c:
        selected = []
        if ids:
            rows = await c.fetch(
                """SELECT id, filename, folder_name, status, created_at, updated_at,
                          left(raw_content, $3) AS excerpt
                   FROM documents
                   WHERE id = ANY($1::uuid[]) AND organization_id = $2""",
                ids, org, SNIPPET_CHARS,
            )
            for r in rows:
                d = _doc_row(r)
                d["excerpt"] = re.sub(r"\s+", " ", r["excerpt"] or "").strip()
                d["changed_since_last_visit"] = bool(
                    since and r["updated_at"] and r["updated_at"] > since
                )
                selected.append(d)

        new_docs = []
        if since:
            rows = await c.fetch(
                """SELECT filename, folder_name, status, created_at
                   FROM documents
                   WHERE organization_id = $1 AND created_at > $2 AND status = 'completed'
                   ORDER BY created_at DESC LIMIT $3""",
                org, since, MAX_NEW_DOCS,
            )
            new_docs = [_doc_row(r) for r in rows]

    return {
        "selected_count": len(document_ids),
        "selected": selected,
        "new_in_org_since_last_visit": new_docs,
    }


# ----------------------------------------------------------------------- LLM
_PROMPT = """You are SoldierIQ, a knowledge assistant for military and defense teams.
The user just signed in. Open the conversation with a short, situational briefing,
before they ask anything. Write it like a sharp staff officer, not a chatbot.

Use the context below. Rules:
- 2 to 5 short sentences, or a greeting line plus up to 3 tight bullets. Markdown allowed.
- Greet by first name if known, matching the time of day.
- Tie the selected documents to the user's situation only when there's a real,
  practical link (e.g. a field manual and severe weather where they are, a
  regional procedure and their location). If there isn't one, mention location
  and weather as one plain factual clause, or leave them out. No metaphors or
  wordplay linking weather to the documents.
- Mention documents that are new or changed since their last visit, if any.
- Morning: frame as a start-of-day brief. Evening or night: frame as a wrap-up.
- If no documents are selected, say so briefly and suggest selecting some in the sidebar.
- Only state facts present in the context. Never invent document contents, locations or events.
- Don't mention that you were given "context", JSON, an IP address or coordinates.

- Don't call it a "first", "initial" or "inaugural" briefing.

Also return up to 3 short follow-up prompts the user could click (each under 60
characters, written as the user would type them). Each must be answerable from
the selected documents listed in the context. If no documents are selected,
return an empty list.

Respond with JSON only: {{"greeting": "...", "suggestions": ["...", ...]}}

<context>
{context}
</context>"""


def _parse(text: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    greeting = (data.get("greeting") or "").strip()
    if not greeting:
        return None
    suggestions = [s.strip() for s in data.get("suggestions") or [] if isinstance(s, str) and s.strip()]
    return {"greeting": greeting, "suggestions": suggestions[:3]}


def _fallback(name: Optional[str], when: Dict[str, Any], docs: Dict[str, Any]) -> Dict[str, Any]:
    hello = f"Good {when['part_of_day'] if when['part_of_day'] != 'night' else 'evening'}"
    hello += f", {name}." if name else "."
    n = docs["selected_count"]
    if n:
        body = f" You have {n} document{'s' if n != 1 else ''} selected. What do you want to work on?"
        suggestions = ["Summarize my selected documents", "What are the key takeaways?", "Quiz me on these documents"]
    else:
        body = " Select some documents in the sidebar and I'll brief you on them."
        suggestions = []
    return {"greeting": hello + body, "suggestions": suggestions}


# ---------------------------------------------------------------------- main
async def generate_briefing(
    *,
    organization_id: str,
    user_id: str,
    first_name: Optional[str],
    latitude: Optional[float],
    longitude: Optional[float],
    timezone_name: Optional[str],
    client_ip: Optional[str],
) -> Dict[str, Any]:
    sel = await document_selection.get_selection(organization_id, user_id)
    doc_ids = sel["document_ids"] if sel else []
    since = sel["last_briefing_at"] if sel else None

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        docs_task = asyncio.create_task(_documents(organization_id, doc_ids, since))
        location = await _locate(client, latitude, longitude, client_ip)
        weather = None
        if location and location.get("latitude") is not None:
            weather = await _weather(client, location["latitude"], location["longitude"])
        docs = await docs_task

    when = _local_time(timezone_name, (location or {}).get("timezone"))
    context = {
        "user_first_name": first_name,
        "time": when,
        "last_visit": since.isoformat() if since else "first briefing",
        "location": {k: v for k, v in (location or {}).items()
                     if k in ("city", "region", "country", "source") and v} or None,
        "weather": weather,
        "documents": docs,
    }

    result = None
    try:
        llm = get_llm(model=BRIEFING_MODEL, provider="openrouter")
        resp = await llm.ainvoke(_PROMPT.format(context=json.dumps(context, default=str, indent=1)))
        result = _parse(resp.content if isinstance(resp.content, str) else str(resp.content))
    except Exception as e:
        logger.warning(f"[briefing] LLM call failed: {e}")
    if not result:
        result = _fallback(first_name, when, docs)
    if not docs["selected_count"]:
        result["suggestions"] = []  # nothing to ground them in

    await document_selection.mark_briefed(organization_id, user_id, datetime.now(timezone.utc))

    loc = context["location"] or {}
    result["context"] = {
        "location": ", ".join(v for v in (loc.get("city"), loc.get("country")) if v) or None,
        "location_source": loc.get("source"),
        "weather": weather and f"{weather['now']}, {weather['temperature_c']}°C",
        "part_of_day": when["part_of_day"],
        "selected_documents": docs["selected_count"],
    }
    return result
