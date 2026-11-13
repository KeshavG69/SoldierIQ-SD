"""Curated conflict datasets: UCDP GED (candidate) and ACLED. Both need accounts."""

from __future__ import annotations

from datetime import date, timedelta

from app.settings import settings
from osint.core import SourceError, cached, get_json, http

UCDP_URL = "https://ucdpapi.pcr.uu.se/api/gedevents/{version}"
UCDP_VERSIONS = ("26.0.10", "26.0.9", "26.0.8", "25.1")  # monthly candidates first, then the annual release
ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_READ_URL = "https://acleddata.com/api/acled/read"

UCDP_VIOLENCE = {1: "state_based", 2: "non_state", 3: "one_sided"}


async def ucdp_events(country: str | None = None, days: int = 365) -> tuple[list[dict], str]:
    """UCDP georeferenced events (verified, published with a lag of weeks to months)."""
    if not settings.UCDP_API_TOKEN:
        raise SourceError("UCDP_API_TOKEN not configured")
    start = (date.today() - timedelta(days=days)).isoformat()

    async def fetch():
        last_err = None
        for version in UCDP_VERSIONS:
            params = {"pagesize": 1000, "StartDate": start}
            if country:
                params["Country"] = country
            try:
                data = await get_json(UCDP_URL.format(version=version), params=params,
                                      headers={"x-ucdp-access-token": settings.UCDP_API_TOKEN}, timeout=40)
            except SourceError as e:
                last_err = e
                continue
            out = []
            for e in data.get("Result") or []:
                out.append({
                    "id": f"ucdp:{e.get('id')}",
                    "date_start": (e.get("date_start") or "")[:10],
                    "date_end": (e.get("date_end") or "")[:10],
                    "country": e.get("country"),
                    "region": e.get("region"),
                    "place": e.get("where_coordinates") or e.get("adm_1"),
                    "lat": e.get("latitude"),
                    "lon": e.get("longitude"),
                    "side_a": e.get("side_a"),
                    "side_b": e.get("side_b"),
                    "violence_type": UCDP_VIOLENCE.get(e.get("type_of_violence")),
                    "deaths_best": e.get("best"),
                    "deaths_low": e.get("low"),
                    "deaths_high": e.get("high"),
                    "source": e.get("source_original"),
                    "dataset_version": version,
                })
            return out
        raise last_err or SourceError("UCDP unavailable")

    return await cached(f"ucdp:{country or 'all'}:{start}", 6 * 3600, fetch)


async def _acled_token() -> str:
    async def fetch():
        try:
            resp = await http().post(ACLED_TOKEN_URL, data={
                "username": settings.ACLED_USERNAME, "password": settings.ACLED_PASSWORD,
                "grant_type": "password", "client_id": "acled",
            }, timeout=30)
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"ACLED token request failed: {type(e).__name__}") from e
        if resp.status_code >= 400:
            raise SourceError(f"ACLED token request returned HTTP {resp.status_code}")
        return resp.json().get("access_token")

    token, _ = await cached("acled:token", 20 * 3600, fetch)
    if not token:
        raise SourceError("ACLED returned no access token")
    return token


async def acled_events(country: str | None = None, days: int = 30) -> tuple[list[dict], str]:
    """ACLED events (political violence and protest, curated, roughly weekly updates)."""
    if not (settings.ACLED_USERNAME and settings.ACLED_PASSWORD):
        raise SourceError("ACLED_USERNAME / ACLED_PASSWORD not configured")
    start = (date.today() - timedelta(days=days)).isoformat()

    async def fetch():
        token = await _acled_token()
        params = {"event_date": f"{start}|{date.today().isoformat()}", "event_date_where": "BETWEEN",
                  "limit": 2000, "_format": "json"}
        if country:
            params["country"] = country
        data = await get_json(ACLED_READ_URL, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=60)
        out = []
        for e in data.get("data") or []:
            out.append({
                "id": f"acled:{e.get('event_id_cnty')}",
                "date": e.get("event_date"),
                "event_type": e.get("event_type"),
                "sub_event_type": e.get("sub_event_type"),
                "actor1": e.get("actor1"),
                "actor2": e.get("actor2"),
                "country": e.get("country"),
                "place": e.get("location"),
                "lat": float(e["latitude"]) if e.get("latitude") else None,
                "lon": float(e["longitude"]) if e.get("longitude") else None,
                "fatalities": int(e.get("fatalities") or 0),
                "notes": (e.get("notes") or "")[:400],
                "source": e.get("source"),
            })
        return out

    return await cached(f"acled:{country or 'all'}:{start}", 3 * 3600, fetch)
