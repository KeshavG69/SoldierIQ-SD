"""News: our outlet register (tier, perspective, state affiliation), RSS reading,
Google News search, and headline clustering.

Tiers (ours): 1 = wire service / newspaper of record / official body;
2 = established outlet or specialist; 3 = partisan, state-aligned or
single-perspective outlet; 4 = state media of a belligerent or propaganda risk.
"""

from __future__ import annotations

import asyncio
import email.utils
import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote_plus, urlparse

from osint.core import SourceError, cached, get_text, iso

GN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _gn(q: str) -> str:
    return GN.format(q=quote_plus(q))


# name, url, tier, home country, type, state affiliation, perspective note
OUTLETS: list[dict] = [
    {"name": "Reuters", "url": _gn("site:reuters.com world when:1d"), "tier": 1, "country": "GB", "type": "wire"},
    {"name": "Associated Press", "url": _gn("site:apnews.com world when:1d"), "tier": 1, "country": "US", "type": "wire"},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "tier": 1, "country": "GB", "type": "public_broadcaster"},
    {"name": "BBC Middle East", "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml", "tier": 1, "country": "GB", "type": "public_broadcaster"},
    {"name": "New York Times World", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "tier": 1, "country": "US", "type": "newspaper"},
    {"name": "UN News", "url": "https://news.un.org/feed/subscribe/en/news/all/rss.xml", "tier": 1, "country": "INTL", "type": "official"},
    {"name": "ReliefWeb", "url": "https://reliefweb.int/updates/rss.xml", "tier": 1, "country": "INTL", "type": "humanitarian"},
    {"name": "The Guardian World", "url": "https://www.theguardian.com/world/rss", "tier": 2, "country": "GB", "type": "newspaper"},
    {"name": "France 24", "url": "https://www.france24.com/en/rss", "tier": 2, "country": "FR", "type": "public_broadcaster"},
    {"name": "Deutsche Welle", "url": "https://rss.dw.com/rdf/rss-en-world", "tier": 2, "country": "DE", "type": "public_broadcaster"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "tier": 2, "country": "QA", "type": "broadcaster", "state": "Qatar", "perspective": "Qatari state-funded"},
    {"name": "Times of Israel", "url": "https://www.timesofisrael.com/feed/", "tier": 2, "country": "IL", "type": "newspaper", "perspective": "Israeli"},
    {"name": "Al-Monitor", "url": "https://www.al-monitor.com/rss", "tier": 2, "country": "US", "type": "specialist"},
    {"name": "Kyiv Independent", "url": "https://kyivindependent.com/feed/", "tier": 2, "country": "UA", "type": "newspaper", "perspective": "Ukrainian"},
    {"name": "Defense News", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/", "tier": 2, "country": "US", "type": "defense"},
    {"name": "Breaking Defense", "url": "https://breakingdefense.com/feed/", "tier": 2, "country": "US", "type": "defense"},
    {"name": "The War Zone", "url": "https://www.twz.com/feed", "tier": 2, "country": "US", "type": "defense"},
    {"name": "USNI News", "url": "https://news.usni.org/feed", "tier": 2, "country": "US", "type": "defense"},
    {"name": "Naval News", "url": "https://www.navalnews.com/feed/", "tier": 2, "country": "FR", "type": "defense"},
    {"name": "Military Times", "url": "https://www.militarytimes.com/arc/outboundfeeds/rss/", "tier": 2, "country": "US", "type": "defense"},
    {"name": "Long War Journal", "url": "https://www.longwarjournal.org/feed", "tier": 2, "country": "US", "type": "analysis", "perspective": "FDD (US hawkish think tank)"},
    {"name": "Crisis Group", "url": "https://www.crisisgroup.org/rss", "tier": 2, "country": "INTL", "type": "analysis"},
    {"name": "Bellingcat", "url": "https://www.bellingcat.com/feed/", "tier": 2, "country": "NL", "type": "osint"},
    {"name": "ISW", "url": _gn("site:understandingwar.org when:3d"), "tier": 2, "country": "US", "type": "analysis"},
    {"name": "The Aviationist", "url": "https://theaviationist.com/feed/", "tier": 3, "country": "IT", "type": "defense"},
    {"name": "Anadolu Agency", "url": "https://www.aa.com.tr/en/rss/default?cat=guncel", "tier": 3, "country": "TR", "type": "wire", "state": "Turkey", "perspective": "Turkish state"},
    {"name": "Arab News", "url": "https://www.arabnews.com/rss.xml", "tier": 3, "country": "SA", "type": "newspaper", "state": "Saudi Arabia", "perspective": "Saudi state-aligned"},
    {"name": "Iran International", "url": _gn("site:iranintl.com when:2d"), "tier": 3, "country": "GB", "type": "broadcaster", "state": "Saudi Arabia", "perspective": "Iranian opposition, Saudi-funded"},
    {"name": "PressTV", "url": "https://www.presstv.ir/rss.xml", "tier": 4, "country": "IR", "type": "state_media", "state": "Iran", "perspective": "Iranian state media"},
    {"name": "TASS", "url": "https://tass.com/rss/v2.xml", "tier": 4, "country": "RU", "type": "state_media", "state": "Russia", "perspective": "Russian state media"},
    {"name": "Xinhua", "url": "http://www.xinhuanet.com/english/rss/worldrss.xml", "tier": 4, "country": "CN", "type": "state_media", "state": "China", "perspective": "Chinese state media"},
]
OUTLET_BY_NAME = {o["name"]: o for o in OUTLETS}

# Domains -> (outlet, tier) for attributing Google News / GDELT results.
DOMAIN_TIERS: dict[str, tuple[str, int]] = {
    "reuters.com": ("Reuters", 1), "apnews.com": ("Associated Press", 1), "bbc.co.uk": ("BBC", 1), "bbc.com": ("BBC", 1),
    "nytimes.com": ("New York Times", 1), "washingtonpost.com": ("Washington Post", 1), "wsj.com": ("Wall Street Journal", 1),
    "ft.com": ("Financial Times", 1), "bloomberg.com": ("Bloomberg", 1), "afp.com": ("AFP", 1), "un.org": ("United Nations", 1),
    "theguardian.com": ("The Guardian", 2), "france24.com": ("France 24", 2), "dw.com": ("Deutsche Welle", 2),
    "aljazeera.com": ("Al Jazeera", 2), "cnn.com": ("CNN", 2), "npr.org": ("NPR", 2), "cbsnews.com": ("CBS News", 2),
    "nbcnews.com": ("NBC News", 2), "abcnews.go.com": ("ABC News", 2), "timesofisrael.com": ("Times of Israel", 2),
    "haaretz.com": ("Haaretz", 2), "jpost.com": ("Jerusalem Post", 3), "al-monitor.com": ("Al-Monitor", 2),
    "kyivindependent.com": ("Kyiv Independent", 2), "defensenews.com": ("Defense News", 2), "breakingdefense.com": ("Breaking Defense", 2),
    "twz.com": ("The War Zone", 2), "news.usni.org": ("USNI News", 2), "understandingwar.org": ("ISW", 2),
    "crisisgroup.org": ("Crisis Group", 2), "bellingcat.com": ("Bellingcat", 2), "politico.com": ("Politico", 2),
    "axios.com": ("Axios", 2), "economist.com": ("The Economist", 1), "lemonde.fr": ("Le Monde", 1),
    "aa.com.tr": ("Anadolu Agency", 3), "arabnews.com": ("Arab News", 3), "iranintl.com": ("Iran International", 3),
    "thenationalnews.com": ("The National", 3), "middleeasteye.net": ("Middle East Eye", 3), "presstv.ir": ("PressTV", 4),
    "tasnimnews.com": ("Tasnim", 4), "farsnews.ir": ("Fars", 4), "tass.com": ("TASS", 4), "rt.com": ("RT", 4),
    "xinhuanet.com": ("Xinhua", 4), "globaltimes.cn": ("Global Times", 4), "kcna.kp": ("KCNA", 4),
}


def domain_tier(url_or_domain: str) -> tuple[Optional[str], Optional[int]]:
    host = urlparse(url_or_domain).netloc or url_or_domain
    host = host.lower().removeprefix("www.")
    for d, (name, tier) in DOMAIN_TIERS.items():
        if host == d or host.endswith("." + d):
            return name, tier
    return None, None


_NAME_TIERS: dict[str, int] = {}
for _name, _tier in DOMAIN_TIERS.values():
    _NAME_TIERS.setdefault(_name.lower(), _tier)
for _o in OUTLETS:
    _NAME_TIERS.setdefault(_o["name"].lower(), _o["tier"])
_NAME_TIERS.update({
    "ap news": 1, "the associated press": 1, "reuters.com": 1, "the new york times": 1, "the washington post": 1,
    "the wall street journal": 1, "financial times": 1, "afp": 1, "bbc news": 1, "the economist": 1, "le monde.fr": 1,
    "al jazeera english": 2, "cnn international": 2, "sky news": 2, "the times of israel": 2, "the jerusalem post": 3,
    "i24news": 3, "middle east eye": 3, "the national": 3, "tasnim news agency": 4, "fars news agency": 4,
    "press tv": 4, "irna": 4, "global times": 4, "rt": 4, "sputnik": 4, "kcna watch": 3, "yahoo": None,
})


def name_tier(publisher: str) -> Optional[int]:
    """Our tier for a publisher name as Google News or GDELT spells it."""
    return _NAME_TIERS.get(publisher.strip().lower())


_TAG = re.compile(r"<[^>]+>")


def clean(text: Optional[str], limit: int = 400) -> str:
    if not text:
        return ""
    t = html.unescape(_TAG.sub(" ", text))
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


def _parse_date(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    try:
        return iso(email.utils.parsedate_to_datetime(s))
    except (TypeError, ValueError):
        pass
    try:
        return iso(datetime.fromisoformat(s.replace("Z", "+00:00")))
    except ValueError:
        return None


def parse_feed(xml_text: str, outlet: dict) -> list[dict]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8", errors="replace"))
    except ET.ParseError as e:
        raise SourceError(f"{outlet['name']} feed is not valid XML") from e
    items = []
    # RSS 2.0 <item>, RSS 1.0 <item> in a namespace, Atom <entry>
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        fields: dict[str, str] = {}
        link = None
        for ch in el:
            ctag = ch.tag.split("}")[-1]
            if ctag == "link":
                link = ch.text or ch.attrib.get("href") or link
            elif ctag in ("title", "description", "summary", "pubDate", "published", "updated", "date", "source"):
                fields.setdefault(ctag, ch.text or "")
        title = clean(fields.get("title"), 300)
        if not title:
            continue
        publisher = clean(fields.get("source"), 80) or None
        if "news.google.com" in outlet["url"]:
            # Google News titles end with " - Publisher"; some publishers add " — Name" too.
            if " - " in title:
                title, _, pub = title.rpartition(" - ")
                publisher = publisher or pub
            for sep in (" — ", " | "):
                if sep in title and len(title.rpartition(sep)[2]) <= 40:
                    title = title.rpartition(sep)[0]
        tier = outlet.get("tier")
        if publisher:
            tier = name_tier(publisher) or domain_tier(link or "")[1] or (tier if "news.google.com" not in outlet["url"] else None)
        items.append({
            "title": title,
            "summary": clean(fields.get("description") or fields.get("summary"), 300),
            "url": (link or "").strip(),
            "published": _parse_date(fields.get("pubDate") or fields.get("published") or fields.get("updated") or fields.get("date")),
            "outlet": publisher or outlet["name"],
            "feed": outlet["name"],
            "tier": tier,
        })
    return items


async def read_feed(outlet: dict, ttl: int = 600) -> tuple[list[dict], str]:
    async def fetch():
        text = await get_text(outlet["url"], timeout=20)
        return parse_feed(text, outlet)

    return await cached(f"rss:{hashlib.md5(outlet['url'].encode()).hexdigest()}", ttl, fetch)


async def read_all_feeds(outlets: Optional[list[dict]] = None) -> tuple[list[dict], list[dict]]:
    """Read many feeds concurrently. Returns (items, per-feed status)."""
    outlets = outlets or OUTLETS
    sem = asyncio.Semaphore(12)

    async def one(o):
        async with sem:
            try:
                items, t = await read_feed(o)
                return o, items, t, None
            except Exception as e:  # noqa: BLE001
                return o, [], None, str(e) if isinstance(e, SourceError) else type(e).__name__

    results = await asyncio.gather(*(one(o) for o in outlets))
    items, status = [], []
    for o, its, t, err in results:
        items.extend(its)
        status.append({"name": o["name"], "url": o["url"], "fetched_at": t, "ok": err is None, **({"error": err} if err else {})})
    return items, status


async def google_news(query: str, when: str = "2d", ttl: int = 900) -> tuple[list[dict], str]:
    """Google News search results for a free-text query (publisher-attributed)."""
    q = f"{query} when:{when}" if when else query
    outlet = {"name": "Google News", "url": _gn(q), "tier": None}

    async def fetch():
        text = await get_text(outlet["url"], timeout=20)
        return parse_feed(text, outlet)

    return await cached(f"gnews:{hashlib.md5(q.lower().encode()).hexdigest()}", ttl, fetch)


# ── Clustering ───────────────────────────────────────────────────────────────

_STOP = set("""a an the of to in on for and or but with at by from as is are was were be been this that these those it its
into over after before about amid says said say new us u.s. will has have had not no more than up out off how what why who
when where which while news live latest report reports update updates video watch""".split())


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9؀-ۿ]+", text.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def cluster_headlines(items: list[dict], threshold: float = 0.34) -> list[dict]:
    """Greedy Jaccard clustering of headlines. Each cluster lists its distinct outlets."""
    clusters: list[dict] = []
    for it in sorted(items, key=lambda x: x.get("published") or "", reverse=True):
        tk = tokens(it["title"])
        if not tk:
            continue
        best, best_sim = None, 0.0
        for c in clusters:
            inter = len(tk & c["_tokens"])
            sim = inter / (len(tk | c["_tokens"]) or 1)
            if sim > best_sim:
                best, best_sim = c, sim
        if best is not None and best_sim >= threshold:
            best["items"].append(it)
            best["_tokens"] |= tk
        else:
            clusters.append({"_tokens": set(tk), "items": [it]})
    out = []
    for c in clusters:
        outlets = sorted({i["outlet"] for i in c["items"]})
        tiers = [i.get("tier") for i in c["items"] if i.get("tier")]
        lead = min(c["items"], key=lambda i: (i.get("tier") or 9, i.get("published") or ""))
        times = sorted(i["published"] for i in c["items"] if i.get("published"))
        independent = len(outlets)
        if independent >= 2 and any(t <= 2 for t in tiers):
            state = "corroborated"
        elif tiers and min(tiers) >= 4:
            state = "state_media_only"
        elif independent == 1:
            state = "single_publisher"
        else:
            state = "multiple_low_tier"
        out.append({
            "headline": lead["title"],
            "lead_outlet": lead["outlet"],
            "url": lead["url"],
            "outlets": outlets,
            "outlet_count": independent,
            "best_tier": min(tiers) if tiers else None,
            "corroboration": state,
            "first_seen": times[0] if times else None,
            "last_seen": times[-1] if times else None,
            "member_headlines": [i["title"] for i in c["items"][:5]],
        })
    out.sort(key=lambda c: (-c["outlet_count"], c["best_tier"] or 9, c["last_seen"] or ""), reverse=False)
    return out


def published_after(items: list[dict], hours: float) -> list[dict]:
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    out = []
    for it in items:
        p = it.get("published")
        if not p:
            continue
        try:
            if datetime.fromisoformat(p.replace("Z", "+00:00")).timestamp() >= cutoff:
                out.append(it)
        except ValueError:
            continue
    return out
