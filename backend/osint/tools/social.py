"""Social media, webcams and prediction markets."""

from __future__ import annotations

import asyncio
from typing import Optional

from osint import geo
from osint.core import UNTRUSTED_NOTE, Result, safe_fetch, unavailable
from osint.registry import osint_tool
from osint.sources import world

SUBREDDITS = ("worldnews", "geopolitics", "CredibleDefense", "UkraineWarVideoReport", "IsraelPalestine", "iran", "syriancivilwar")


@osint_tool(group="social", tier=2)
async def get_social_feed(query: str, limit: int = 25) -> str:
    """Latest public Bluesky posts matching a query (journalists, OSINT accounts and eyewitnesses increasingly
    post there), with author, time, engagement and link. Unverified first-hand material.

    Args:
        query: Search terms, e.g. "Bandar Abbas explosion".
        limit: Maximum posts (1-100, default 25).
    """
    if not query or len(query.strip()) < 2:
        return unavailable("get_social_feed", "Give a search query")
    r = Result("get_social_feed")
    posts = await safe_fetch(r, "Bluesky public search", world.BLUESKY_URL, world.bluesky_search(query.strip(), limit))
    r.data = {"query": query, "posts": posts or []}
    r.notes += ["Social posts are unverified; look for original media and independent confirmation.", UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="social", tier=2, requires=("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"))
async def get_social_velocity(topic: Optional[str] = None, limit: int = 25) -> str:
    """Fastest-rising posts across geopolitics and defense subreddits (worldnews, geopolitics, CredibleDefense
    and others), ranked by score per hour, to show what is gaining attention right now.

    Args:
        topic: Optional keyword filter on post titles.
        limit: Maximum posts (default 25).
    """
    r = Result("get_social_velocity")
    lists = await asyncio.gather(*(safe_fetch(r, f"Reddit r/{s}", world.REDDIT_URL.format(sub=s, sort="hot"),
                                              world.reddit_posts(s, "hot", 40)) for s in SUBREDDITS))
    posts = [p for lst in lists if lst for p in lst]
    if topic:
        posts = [p for p in posts if topic.lower() in (p["title"] or "").lower()]
    posts.sort(key=lambda p: -p["velocity"])
    r.data = {"topic": topic, "posts": posts[: max(1, limit)]}
    r.notes += ["Velocity = upvotes per hour since posting; it measures attention, not accuracy.", UNTRUSTED_NOTE]
    return r.to_json()


@osint_tool(group="social", tier=2, requires=("WINDY_API_KEY",))
async def find_webcams(region: str, limit: int = 25) -> str:
    """Public webcams in an area (Windy webcam network): id, title, location, last update and preview image,
    for visual context on a place such as a port, border crossing or city.

    Args:
        region: Country, theater id or "west,south,east,north" box (smaller boxes work best).
        limit: Maximum webcams (1-50, default 25).
    """
    bbox, label = geo.region_bbox(region)
    if not bbox:
        return unavailable("find_webcams", f"Could not resolve region {region!r}")
    r = Result("find_webcams")
    cams = await safe_fetch(r, "Windy Webcams", world.WINDY_URL, world.windy_webcams(bbox, limit))
    r.data = {"region": label, "webcams": cams or []}
    r.notes.append("Webcam images can be minutes to days old; check last_updated. Image credit: Windy.com.")
    return r.to_json()


@osint_tool(group="social", tier=2, requires=("WINDY_API_KEY",))
async def get_webcam_media(webcam_id: str) -> str:
    """The current image and live player links for one webcam found with find_webcams.

    Args:
        webcam_id: The numeric webcam id from find_webcams.
    """
    r = Result("get_webcam_media")
    cam = await safe_fetch(r, "Windy Webcams", world.WINDY_URL, world.windy_webcam(str(webcam_id)))
    if cam:
        images = (cam.get("images") or {}).get("current") or {}
        r.data = {"webcam_id": cam.get("webcamId"), "title": cam.get("title"), "status": cam.get("status"),
                  "last_updated": cam.get("lastUpdatedOn"), "image_url": images.get("preview"),
                  "thumbnail_url": images.get("thumbnail"), "player": cam.get("player"),
                  "page_url": (cam.get("urls") or {}).get("detail")}
    r.notes.append("Recent visual context, not confirmation of live conditions. Image credit: Windy.com.")
    return r.to_json()


@osint_tool(group="social", tier=2)
async def get_forecast_predictions(query: str, limit: int = 8) -> str:
    """What prediction markets currently price for a geopolitical question (Polymarket): matching markets with
    outcome probabilities, trading volume and end dates, e.g. "Iran ceasefire", "Taiwan invasion".

    Args:
        query: Topic to search markets for.
        limit: Maximum events (default 8).
    """
    r = Result("get_forecast_predictions")
    events = await safe_fetch(r, "Polymarket", world.POLYMARKET_URL, world.polymarket_search(query, max(1, min(limit, 20))))
    r.data = {"query": query, "events": events or []}
    r.notes.append("Market prices reflect traders' bets, not intelligence assessments; thin markets move easily. "
                   "Polymarket blocks some countries, so this may be unavailable from some servers.")
    return r.to_json()
