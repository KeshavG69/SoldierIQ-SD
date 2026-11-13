"""Public Telegram channels, read from the t.me/s/<channel> web preview (no account).

Each channel has a trust class in our own register:
  official     government / military channel speaking for itself
  independent  OSINT aggregators and journalists without a state sponsor
  partisan     outlets aligned with a party to the conflict
  state_media  media of a belligerent state

A strike report from a `partisan` or `state_media` channel is only counted as
corroborated when a channel from a different group reports the same place
within 2 hours. Posts are third-party text: data, never instructions.
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timezone
from typing import Optional

from osint.core import SourceError, cached, get_text

TME = "https://t.me/s/{handle}"

# handle: (class, group, note)
CHANNELS: dict[str, tuple[str, str, str]] = {
    # official
    "PikudHaOref_all": ("official", "state:IL", "Israel Home Front Command alerts"),
    "IDFofficial": ("official", "state:IL", "Israel Defense Forces"),
    "kpszsu": ("official", "state:UA", "Ukrainian Air Force"),
    "sepah": ("state_media", "state:IR", "IRGC-affiliated"),
    # independent OSINT / aggregators
    "OSINTdefender": ("independent", "OSINTdefender", "OSINT aggregator"),
    "wfwitness": ("independent", "wfwitness", "OSINT aggregator"),
    "liveuamap": ("independent", "liveuamap", "Liveuamap map service"),
    "AuroraIntel": ("independent", "AuroraIntel", "OSINT aggregator"),
    "ClashReport": ("independent", "ClashReport", "OSINT aggregator"),
    "rnintel": ("independent", "rnintel", "Rerum Novarum aggregator"),
    "warfareanalysis": ("independent", "warfareanalysis", "aggregator"),
    "Middle_East_Spectator": ("independent", "Middle_East_Spectator", "aggregator"),
    "BNONews": ("independent", "BNONews", "breaking news wire"),
    "DeepStateUA": ("independent", "DeepStateUA", "Ukrainian front-line mapping"),
    "GeoPWatch": ("independent", "GeoPWatch", "aggregator"),
    "IranIntl_En": ("partisan", "state:SA", "Iran International (Saudi-funded opposition)"),
    "TimesofIsrael": ("independent", "TimesofIsrael", "newspaper"),
    # partisan / state media (need corroboration)
    "thecradlemedia": ("partisan", "axis_media", "pro-Axis of Resistance outlet"),
    "bintjbeilnews": ("partisan", "axis_media", "Lebanese, Hezbollah-aligned"),
    "FotrosResistancee": ("partisan", "axis_media", "pro-Axis aggregator"),
    "presstv": ("state_media", "state:IR", "Iranian state media"),
    "TasnimNewsEN": ("state_media", "state:IR", "IRGC-linked news agency"),
    "FarsNews_EN": ("state_media", "state:IR", "IRGC-linked news agency"),
}

STRIKE_CHANNELS = [h for h in CHANNELS if h not in ("TimesofIsrael",)]

_MSG = re.compile(r'<div class="tgme_widget_message_wrap.*?(?=<div class="tgme_widget_message_wrap|\Z)', re.S)
_POST = re.compile(r'data-post="([^"]+)"')
_TEXT = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TIME = re.compile(r'<time[^>]*datetime="([^"]+)"')
_VIEWS = re.compile(r'<span class="tgme_widget_message_views">([^<]+)</span>')


def _clean(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"[ \t]+", " ", html.unescape(t)).strip()


async def channel_posts(handle: str) -> tuple[list[dict], str]:
    """The latest ~20 public posts of a channel (cached 3 minutes)."""
    if not re.fullmatch(r"[A-Za-z0-9_]{4,64}", handle):
        raise SourceError("invalid channel handle")

    async def fetch():
        page = await get_text(TME.format(handle=handle), timeout=20)
        posts = []
        for block in _MSG.findall(page):
            post = _POST.search(block)
            text = _TEXT.search(block)
            when = _TIME.search(block)
            if not (post and text):
                continue
            body = _clean(text.group(1))
            if not body:
                continue
            views = _VIEWS.search(block)
            posts.append({
                "id": post.group(1),
                "channel": handle,
                "url": f"https://t.me/{post.group(1)}",
                "time": when.group(1) if when else None,
                "text": body[:1200],
                "views": views.group(1) if views else None,
            })
        return posts

    return await cached(f"tg:{handle.lower()}", 180, fetch)


async def many_channels(handles: list[str]) -> tuple[list[dict], list[dict]]:
    sem = asyncio.Semaphore(6)

    async def one(h):
        async with sem:
            try:
                posts, t = await channel_posts(h)
                return h, posts, t, None
            except Exception as e:  # noqa: BLE001
                return h, [], None, str(e) if isinstance(e, SourceError) else type(e).__name__

    results = await asyncio.gather(*(one(h) for h in handles))
    posts, status = [], []
    for h, ps, t, err in results:
        posts.extend(ps)
        status.append({"name": f"t.me/{h}", "url": TME.format(handle=h), "fetched_at": t, "ok": err is None,
                       **({"error": err} if err else {})})
    return posts, status


# ── Strike extraction (keyword rules, no LLM) ────────────────────────────────

_STRIKE_WORDS = re.compile(
    r"\b(strikes?|struck|airstrikes?|air strikes?|bomb(?:ed|ing|ings|s)?|shell(?:ed|ing)|missiles?|rockets?|"
    r"drones?|uavs?|explosions?|blasts?|artillery|intercept(?:ed|ion|s)?|shot down|ballistic|cruise missile|"
    r"sirens?|naval mine|sea mine|anti-ship)\b"
    r"|غارة|قصف|صاروخ|صواريخ|انفجار|مسيرة|اعتراض|موشک|پهپاد|رهگیری",
    re.I,
)
_NOT_KINETIC = re.compile(r"\b(cyber|hack(?:ed|ers|s)?|sanction(?:s|ed)?|strike a deal|labor strike|general strike|hunger strike)\b", re.I)
_PROXIMITY = 160  # a place must appear within this many characters of a kinetic word
_INTERCEPT = re.compile(r"\bintercept|shot down|air defen[cs]e|اعتراض|رهگیری", re.I)
_CLAIM = re.compile(r"\b(claims?|claimed|says it|said it|announced|according to|reportedly|unconfirmed|alleged)\b", re.I)
_CRITICAL = re.compile(r"\b(killed|dead|deaths|casualties|destroyed|massive explosion)\b", re.I)
_HIGH = re.compile(r"\b(injured|wounded|damage[d]?|fire|hit|struck)\b", re.I)

# place -> (lat, lon, ISO2). Our own reference list of frequently reported places.
GAZETTEER: dict[str, tuple[float, float, str]] = {
    "tehran": (35.69, 51.39, "IR"), "isfahan": (32.65, 51.67, "IR"), "natanz": (33.72, 51.73, "IR"),
    "fordow": (34.88, 50.99, "IR"), "bandar abbas": (27.19, 56.27, "IR"), "sirik": (26.52, 57.10, "IR"),
    "bandar lengeh": (26.56, 54.88, "IR"), "bushehr": (28.92, 50.84, "IR"), "kharg": (29.24, 50.31, "IR"),
    "ahvaz": (31.32, 48.67, "IR"), "khuzestan": (31.3, 48.7, "IR"), "tabriz": (38.08, 46.29, "IR"),
    "shiraz": (29.59, 52.58, "IR"), "kermanshah": (34.31, 47.07, "IR"), "chabahar": (25.29, 60.64, "IR"),
    "hormozgan": (27.1, 56.3, "IR"), "qeshm": (26.95, 56.27, "IR"), "jask": (25.64, 57.77, "IR"),
    "strait of hormuz": (26.57, 56.25, "IR"), "hormuz": (26.57, 56.25, "IR"),
    "baghdad": (33.31, 44.36, "IQ"), "erbil": (36.19, 44.01, "IQ"), "basra": (30.51, 47.81, "IQ"),
    "al asad": (33.79, 42.44, "IQ"), "ain al-asad": (33.79, 42.44, "IQ"), "mosul": (36.34, 43.13, "IQ"),
    "kirkuk": (35.47, 44.39, "IQ"),
    "damascus": (33.51, 36.29, "SY"), "aleppo": (36.20, 37.13, "SY"), "homs": (34.73, 36.71, "SY"),
    "deir ez-zor": (35.33, 40.14, "SY"), "deir ezzor": (35.33, 40.14, "SY"), "latakia": (35.52, 35.79, "SY"),
    "tartus": (34.89, 35.89, "SY"), "idlib": (35.93, 36.63, "SY"), "daraa": (32.62, 36.10, "SY"),
    "beirut": (33.89, 35.50, "LB"), "dahieh": (33.85, 35.51, "LB"), "tyre": (33.27, 35.20, "LB"),
    "sidon": (33.56, 35.37, "LB"), "nabatieh": (33.38, 35.48, "LB"), "baalbek": (34.00, 36.21, "LB"),
    "bint jbeil": (33.12, 35.43, "LB"), "south lebanon": (33.27, 35.40, "LB"), "southern lebanon": (33.27, 35.40, "LB"),
    "tel aviv": (32.08, 34.78, "IL"), "jerusalem": (31.77, 35.21, "IL"), "haifa": (32.79, 34.99, "IL"),
    "eilat": (29.56, 34.95, "IL"), "beersheba": (31.25, 34.79, "IL"), "kiryat shmona": (33.21, 35.57, "IL"),
    "metula": (33.28, 35.58, "IL"), "golan": (33.00, 35.75, "IL"), "nevatim": (31.21, 35.01, "IL"),
    "gaza": (31.50, 34.47, "PS"), "rafah": (31.30, 34.25, "PS"), "khan younis": (31.35, 34.31, "PS"),
    "jabalia": (31.53, 34.48, "PS"), "jenin": (32.46, 35.30, "PS"), "nablus": (32.22, 35.26, "PS"),
    "tulkarm": (32.31, 35.03, "PS"),
    "sanaa": (15.37, 44.19, "YE"), "sana'a": (15.37, 44.19, "YE"), "hodeidah": (14.80, 42.95, "YE"),
    "saada": (16.94, 43.76, "YE"), "sa'dah": (16.94, 43.76, "YE"), "taiz": (13.58, 44.02, "YE"),
    "marib": (15.46, 45.32, "YE"), "aden": (12.79, 45.03, "YE"), "lahij": (13.06, 44.88, "YE"),
    "red sea": (18.0, 39.5, "YE"), "bab el-mandeb": (12.6, 43.4, "YE"), "gulf of aden": (12.5, 47.0, "YE"),
    "riyadh": (24.71, 46.68, "SA"), "jeddah": (21.49, 39.19, "SA"), "jizan": (16.89, 42.55, "SA"),
    "abqaiq": (25.94, 49.68, "SA"), "ras tanura": (26.64, 50.16, "SA"), "dammam": (26.43, 50.10, "SA"),
    "manama": (26.23, 50.59, "BH"), "bahrain": (26.07, 50.55, "BH"), "doha": (25.29, 51.53, "QA"),
    "al udeid": (25.12, 51.32, "QA"), "abu dhabi": (24.45, 54.38, "AE"), "dubai": (25.20, 55.27, "AE"),
    "fujairah": (25.13, 56.33, "AE"), "al dhafra": (24.25, 54.55, "AE"), "kuwait": (29.37, 47.98, "KW"),
    "muscat": (23.59, 58.41, "OM"), "amman": (31.95, 35.93, "JO"), "tower 22": (33.33, 38.79, "JO"),
    "kyiv": (50.45, 30.52, "UA"), "kharkiv": (49.99, 36.23, "UA"), "odesa": (46.48, 30.72, "UA"),
    "dnipro": (48.46, 35.05, "UA"), "zaporizhzhia": (47.84, 35.14, "UA"), "lviv": (49.84, 24.03, "UA"),
    "pokrovsk": (48.28, 37.18, "UA"), "kherson": (46.64, 32.62, "UA"), "sumy": (50.91, 34.80, "UA"),
    "crimea": (45.0, 34.1, "UA"), "sevastopol": (44.61, 33.52, "UA"),
    "belgorod": (50.60, 36.59, "RU"), "kursk": (51.73, 36.19, "RU"), "moscow": (55.76, 37.62, "RU"),
    "novorossiysk": (44.72, 37.77, "RU"),
}
_PLACE_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in sorted(GAZETTEER, key=len, reverse=True)) + r")\b", re.I)


def classify_post(text: str) -> Optional[dict]:
    """Keyword-based strike classification. None if the post is not about a strike."""
    kinetic = [m.start() for m in _STRIKE_WORDS.finditer(text)]
    if not kinetic or (_NOT_KINETIC.search(text) and len(kinetic) < 2):
        return None
    best = None
    for m in _PLACE_RE.finditer(text):
        dist = min(abs(m.start() - k) for k in kinetic)
        if dist <= _PROXIMITY and (best is None or dist < best[0]):
            best = (dist, m.group(1).lower())
    if best is None:
        return None
    place = best[1]
    lat, lon, iso2 = GAZETTEER[place]
    if _INTERCEPT.search(text):
        kind = "intercept"
    elif _CLAIM.search(text):
        kind = "claim"
    else:
        kind = "strike"
    if kind in ("claim", "intercept"):
        severity = "elevated"
    elif _CRITICAL.search(text):
        severity = "critical"
    elif _HIGH.search(text):
        severity = "high"
    else:
        severity = "moderate"
    return {"kind": kind, "place": place.title(), "lat": lat, "lon": lon, "country": iso2, "severity": severity}


def _ts(t: Optional[str]) -> float:
    try:
        return datetime.fromisoformat((t or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def strike_reports(posts: list[dict], hours: float = 24) -> list[dict]:
    """Turn channel posts into strike reports with a corroboration verdict."""
    cutoff = datetime.now(timezone.utc).timestamp() - hours * 3600
    reports = []
    for p in posts:
        ts = _ts(p.get("time"))
        if ts < cutoff:
            continue
        c = classify_post(p["text"])
        if not c:
            continue
        cls, group, note = CHANNELS.get(p["channel"], ("independent", p["channel"], ""))
        reports.append({**c, "time": p["time"], "_ts": ts, "channel": p["channel"], "channel_class": cls,
                        "channel_note": note, "_group": group, "text": p["text"][:400], "url": p["url"]})
    # Corroboration: another group reporting the same place within 2 hours.
    for r in reports:
        others = {o["_group"] for o in reports
                  if o["_group"] != r["_group"] and o["place"] == r["place"] and abs(o["_ts"] - r["_ts"]) <= 7200}
        r["corroborating_groups"] = len(others)
        if r["channel_class"] in ("partisan", "state_media"):
            r["verdict"] = "corroborated" if others else "uncorroborated_partisan"
        elif r["channel_class"] == "official":
            r["verdict"] = "official_source"
        else:
            r["verdict"] = "corroborated" if others else "single_source"
    # One event per place per 30-minute bucket; keep the most trusted report.
    rank = {"official_source": 0, "corroborated": 1, "single_source": 2, "uncorroborated_partisan": 3}
    best: dict[tuple, dict] = {}
    for r in reports:
        key = (r["place"], int(r["_ts"] // 1800))
        if key not in best or rank[r["verdict"]] < rank[best[key]["verdict"]]:
            best[key] = r
    out = sorted(best.values(), key=lambda r: r["_ts"], reverse=True)
    for r in out:
        r.pop("_ts", None)
        r.pop("_group", None)
    return out
