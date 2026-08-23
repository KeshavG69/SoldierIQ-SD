"""
YouTube transcript fetcher (youtube-transcript-api).

Pulls captions straight from YouTube's caption endpoint — no video download —
so it sidesteps the bot-check / 403 that blocks yt-dlp's video streams. Used as
the PRIMARY path for YouTube ingestion; the video download is only a fallback
for videos with no captions.

Datacenter IPs (Railway, AWS, GCP…) are blocked by YouTube on the caption
endpoint too, which surfaces as RequestBlocked / IpBlocked. There is no free
code-only flag that bypasses this — the block is on the IP. The free lever you
control is COOKIES from a logged-in account: export them to a Netscape
cookies.txt and set YOUTUBE_COOKIES_FILE; they authenticate the request so
YouTube is more likely to treat it as a real viewer. A residential proxy
(YOUTUBE_PROXY, or WEBSHARE_PROXY_USERNAME/PASSWORD) is the bulletproof — but
paid — alternative. Env vars are read here so the transcript and download paths
share one configuration.
"""

import os
import re
from typing import Optional
from app.logger import logger


_ID_PATTERNS = [
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
]

# Exceptions that mean "this IP is blocked" (add a proxy or cookies) vs
# "this video genuinely has no captions" (fall back to the video download).
_BLOCKED_ERRORS = {"RequestBlocked", "IpBlocked", "YouTubeRequestFailed"}
_NO_CAPTIONS_ERRORS = {
    "TranscriptsDisabled",
    "NoTranscriptFound",
    "VideoUnavailable",
    "VideoUnplayable",
    "AgeRestricted",
}


def extract_video_id(url: str) -> Optional[str]:
    """Pull the 11-char video id out of any common YouTube URL form."""
    if not url:
        return None
    for pat in _ID_PATTERNS:
        m = re.search(pat, url)
        if m:
            return m.group(1)
    # Bare id passed directly?
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url.strip()):
        return url.strip()
    return None


def _build_http_client():
    """A requests.Session carrying YouTube cookies (free auth lever) and/or a
    generic proxy, or None when neither is configured. Passed to the transcript
    API so the caption request looks like a signed-in viewer."""
    cookies_file = os.getenv("YOUTUBE_COOKIES_FILE")
    proxy = os.getenv("YOUTUBE_PROXY")
    have_cookies = bool(cookies_file and os.path.exists(cookies_file))
    if not have_cookies and not proxy:
        return None
    try:
        import http.cookiejar
        import requests

        session = requests.Session()
        if have_cookies:
            jar = http.cookiejar.MozillaCookieJar(cookies_file)
            jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies = jar  # type: ignore[assignment]
            logger.info("🔐 Transcript fetch using YouTube cookies file")
        if proxy:
            session.proxies = {"http": proxy, "https": proxy}
            logger.info("🌐 Transcript fetch routing through configured proxy")
        return session
    except Exception as e:
        logger.warning(f"[yt-transcript] cookie/proxy session setup failed: {e}")
        return None


def _build_proxy_config():
    """Webshare residential proxy config (recommended by the library for cloud
    IPs), or None. Generic http proxies are handled on the session instead."""
    ws_user = os.getenv("WEBSHARE_PROXY_USERNAME")
    ws_pass = os.getenv("WEBSHARE_PROXY_PASSWORD")
    if ws_user and ws_pass:
        try:
            from youtube_transcript_api.proxies import WebshareProxyConfig

            return WebshareProxyConfig(proxy_username=ws_user, proxy_password=ws_pass)
        except Exception as e:
            logger.warning(f"[yt-transcript] Webshare proxy config unavailable: {e}")
    return None


def _make_api(proxy_config, http_client):
    """Construct YouTubeTranscriptApi, tolerating older signatures that don't
    accept proxy_config / http_client."""
    from youtube_transcript_api import YouTubeTranscriptApi

    try:
        return YouTubeTranscriptApi(proxy_config=proxy_config, http_client=http_client)
    except TypeError:
        # Older library: no proxy/cookie support — best-effort default.
        return YouTubeTranscriptApi()


def fetch_transcript(video_id: str) -> Optional[str]:
    """Return the full transcript text for a video, or None if it has no
    captions or the request is blocked. Never raises.

    On a datacenter IP a None return is usually a *block*, not a missing
    transcript — the log line distinguishes the two so the operator knows
    whether to add cookies/a proxy or accept that the video has no captions."""
    if not video_id:
        return None

    http_client = _build_http_client()
    # Generic proxy already rides on the session; only pass a Webshare config
    # when we didn't build a session for it.
    proxy_config = None if http_client else _build_proxy_config()

    try:
        api = _make_api(proxy_config, http_client)
        fetched = api.fetch(video_id)
        snippets = getattr(fetched, "snippets", None) or list(fetched)
        parts = []
        for s in snippets:
            txt = getattr(s, "text", None)
            if txt is None and isinstance(s, dict):
                txt = s.get("text")
            if txt and txt.strip():
                parts.append(txt.strip())
        text = " ".join(parts).strip()
        if not text:
            logger.info(f"[yt-transcript] {video_id}: transcript empty")
            return None
        logger.info(f"[yt-transcript] {video_id}: fetched {len(text)} chars from captions")
        return text
    except Exception as e:
        name = type(e).__name__
        if name in _BLOCKED_ERRORS:
            logger.warning(
                f"[yt-transcript] {video_id}: YouTube blocked this IP on the caption "
                f"endpoint ({name}). This video HAS captions — the datacenter IP is the "
                f"problem. Set YOUTUBE_COOKIES_FILE (free) or a residential proxy "
                f"(YOUTUBE_PROXY / WEBSHARE_PROXY_USERNAME+PASSWORD) to fetch them."
            )
        elif name in _NO_CAPTIONS_ERRORS:
            logger.info(f"[yt-transcript] {video_id}: no captions available ({name})")
        else:
            logger.info(
                f"[yt-transcript] {video_id}: transcript fetch failed ({name}: {str(e)[:120]})"
            )
        return None


# ---------------------------------------------------------------------------
# Hosted fallback — the free path that works from a blocked datacenter IP.
# ---------------------------------------------------------------------------
# youtube-transcript-api runs on OUR IP, so it dies when YouTube blocks the
# datacenter. A hosted transcript endpoint runs on ITS OWN (unblocked) IP and
# needs no key/cookies/proxy on our side — the free way to fetch captions from
# Railway. Default provider: youtube-transcript.ai (no signup, fair-use). It is
# a third party: the (public) video id is sent to them. Override the provider
# with YOUTUBE_TRANSCRIPT_API_URL, add a token via YOUTUBE_TRANSCRIPT_API_BEARER,
# or disable by setting YOUTUBE_TRANSCRIPT_API_URL="".

_DEFAULT_HOSTED_URL = "https://youtube-transcript.ai/transcript/{video_id}.txt"


def _collapse_repeats(text: str) -> str:
    """Collapse the rolling-caption triplication auto-generated transcripts
    carry (a phrase repeated 2-3× back-to-back). Best-effort, order-preserving."""
    words = text.split()
    n = len(words)
    out: list[str] = []
    i = 0
    while i < n:
        matched = False
        # Longest immediate phrase repeat first, so we don't collapse partials.
        # Multi-word phrases collapse on a single repeat; single words need a
        # true triple, so intentional "that that" / "no no" survive.
        for L in range(min(14, (n - i) // 2), 0, -1):
            phrase = words[i : i + L]
            reps = 1
            while words[i + reps * L : i + (reps + 1) * L] == phrase:
                reps += 1
            if reps >= (3 if L == 1 else 2):
                out.extend(phrase)
                i += reps * L
                matched = True
                break
        if not matched:
            out.append(words[i])
            i += 1
    return " ".join(out)


def _clean_hosted(raw: str) -> str:
    """Strip the provider's metadata header, timestamps, and sound tags, then
    de-duplicate rolling captions. Keeps the video title as a leading line."""
    title = None
    m = re.search(r"^#\s*Transcript:\s*(.+)$", raw, re.M)
    if m:
        title = m.group(1).strip()
    idx = raw.find("## Transcript")
    body = raw[idx + len("## Transcript") :] if idx != -1 else raw
    # Drop the provider's promo footer ("--- Generated by … Interactive version …").
    body = re.split(r"-{2,}\s*Generated by", body)[0]
    body = re.sub(r"Interactive version \([^)]*\):\s*https?://\S+", " ", body)
    body = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", " ", body)  # [m:ss] / [h:mm:ss]
    body = re.sub(r"\[(?:Music|Applause|Laughter|Inaudible|__)\]", " ", body, flags=re.I)
    body = re.sub(r"\s+", " ", body).strip()
    body = _collapse_repeats(body)
    return (f"{title}\n\n{body}" if title else body).strip()


def fetch_transcript_hosted(video_id: str) -> Optional[str]:
    """Fetch captions via a hosted transcript endpoint (runs on an unblocked
    IP). Returns cleaned text or None. Never raises."""
    if not video_id:
        return None
    url_tmpl = os.getenv("YOUTUBE_TRANSCRIPT_API_URL", _DEFAULT_HOSTED_URL)
    if not url_tmpl:  # explicitly disabled
        return None
    url = url_tmpl.format(video_id=video_id)
    headers = {"User-Agent": "SoldierIQ/1.0 (+knowledge-ingest)"}
    bearer = os.getenv("YOUTUBE_TRANSCRIPT_API_BEARER")
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    try:
        import httpx

        with httpx.Client(timeout=45.0, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 429:
            logger.warning(f"[yt-transcript-hosted] {video_id}: rate limited (HTTP 429)")
            return None
        if resp.status_code != 200:
            logger.warning(f"[yt-transcript-hosted] {video_id}: HTTP {resp.status_code}")
            return None
        text = _clean_hosted(resp.text or "")
        if len(text) < 20:
            logger.info(f"[yt-transcript-hosted] {video_id}: empty/too-short response")
            return None
        logger.info(f"[yt-transcript-hosted] {video_id}: fetched {len(text)} chars via hosted endpoint")
        return text
    except Exception as e:
        logger.warning(
            f"[yt-transcript-hosted] {video_id}: request failed ({type(e).__name__}: {str(e)[:120]})"
        )
        return None
