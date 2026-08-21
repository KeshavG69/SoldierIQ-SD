"""
YouTube transcript fetcher (youtube-transcript-api).

Pulls captions straight from YouTube's caption endpoint — no video download —
so it sidesteps the bot-check / 403 that blocks yt-dlp's video streams from a
datacenter IP. Used as the PRIMARY path for YouTube ingestion; the video
download is only a fallback for videos with no captions.
"""

import re
from typing import Optional
from app.logger import logger


_ID_PATTERNS = [
    r"(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})",
]


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


def fetch_transcript(video_id: str) -> Optional[str]:
    """Return the full transcript text for a video, or None if it has no
    captions (or they can't be fetched). Never raises."""
    if not video_id:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
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
        # NoTranscriptFound / TranscriptsDisabled / network — all non-fatal;
        # the caller falls back to the video-download path.
        logger.info(f"[yt-transcript] {video_id}: no usable transcript ({type(e).__name__}: {str(e)[:120]})")
        return None
