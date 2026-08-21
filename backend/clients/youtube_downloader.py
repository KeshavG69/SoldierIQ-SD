"""
YouTube Downloader Client
Downloads YouTube videos using yt-dlp
"""

import tempfile
import os
import random
from typing import Tuple, Optional
from app.logger import logger

try:
    import yt_dlp
except ImportError:
    raise ImportError("yt-dlp is required. Install it with: pip install yt-dlp")


class YouTubeDownloader:
    """YouTube video downloader using yt-dlp"""

    # User agents for rotation to avoid bot detection
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0',
        'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1.1 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_14_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/107.0.0.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_9) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15',
    ]

    def __init__(self):
        """Initialize YouTube downloader"""
        self.ydl_opts = {
            # Download 720p MP4 for balance between quality and file size
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]',
            'outtmpl': '%(id)s.%(ext)s',
            'quiet': False,
            'no_warnings': False,
            'extract_flat': False,
            # Anti-bot detection: Add sleep intervals (CRITICAL)
            'sleep_interval': 2,           # Wait 2 seconds between requests
            'max_sleep_interval': 5,       # Random delay up to 5 seconds
            # Rate limiting to appear more natural
            'ratelimit': 2000000,          # Limit to 2MB/s (adjust as needed)
            # Retry settings
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
            # Anti-403: YouTube's "SABR-only" experiment makes the default web
            # formats 403 on download. The ios / tv / mweb player clients serve
            # non-gated progressive formats, so prefer them. (If 403s persist,
            # update yt-dlp — YouTube changes often and yt-dlp ships fixes.)
            'extractor_args': {
                'youtube': {
                    'player_client': ['ios', 'tv', 'mweb', 'web_safari'],
                }
            },
        }

    def download_video(self, youtube_url: str) -> Tuple[bytes, str, dict]:
        """
        Download YouTube video and return as bytes

        Args:
            youtube_url: YouTube video URL

        Returns:
            Tuple of (video_bytes, filename, metadata)
            - video_bytes: Video file content as bytes
            - filename: Generated filename (title + .mp4)
            - metadata: Video metadata (title, duration, uploader, etc.)

        Raises:
            Exception: If download fails
        """
        logger.info(f"📥 Downloading YouTube video: {youtube_url}")

        temp_dir = tempfile.mkdtemp()

        try:
            # Randomly select a user agent to avoid bot detection
            user_agent = random.choice(self.USER_AGENTS)
            logger.debug(f"Using User-Agent: {user_agent[:50]}...")

            # Configure download options
            ydl_opts = {
                **self.ydl_opts,
                'outtmpl': os.path.join(temp_dir, '%(id)s.%(ext)s'),
                'http_headers': {
                    'User-Agent': user_agent,
                },
            }

            # Cookies for YouTube's bot-check. As of 2026 YouTube blocks most
            # server-side downloads ("The page needs to be reloaded" / 403)
            # unless the request is authenticated. Export cookies from a
            # logged-in browser to a Netscape cookies.txt and point
            # YOUTUBE_COOKIES_FILE at it (or set YOUTUBE_COOKIES_FROM_BROWSER
            # to e.g. "chrome" when a browser is available on the host).
            cookies_file = os.getenv("YOUTUBE_COOKIES_FILE")
            cookies_browser = os.getenv("YOUTUBE_COOKIES_FROM_BROWSER")
            if cookies_file and os.path.exists(cookies_file):
                ydl_opts['cookiefile'] = cookies_file
                logger.info("🔐 Using YouTube cookies file for authenticated download")
            elif cookies_browser:
                ydl_opts['cookiesfrombrowser'] = (cookies_browser,)
                logger.info(f"🔐 Using YouTube cookies from browser: {cookies_browser}")

            # Download video
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract info first
                info = ydl.extract_info(youtube_url, download=True)

                # Get metadata
                video_id = info.get('id')
                title = info.get('title', 'Untitled')
                duration = info.get('duration', 0)
                uploader = info.get('uploader', 'Unknown')
                upload_date = info.get('upload_date', '')
                description = info.get('description', '')

                metadata = {
                    'video_id': video_id,
                    'title': title,
                    'duration': duration,
                    'uploader': uploader,
                    'upload_date': upload_date,
                    'description': description,
                    'url': youtube_url,
                }

                # Find downloaded file
                downloaded_file = None
                for file in os.listdir(temp_dir):
                    if file.startswith(video_id):
                        downloaded_file = os.path.join(temp_dir, file)
                        break

                if not downloaded_file or not os.path.exists(downloaded_file):
                    raise FileNotFoundError(f"Downloaded video file not found for video ID: {video_id}")

                # Read file content
                with open(downloaded_file, 'rb') as f:
                    video_bytes = f.read()

                # Generate safe filename
                safe_title = self._sanitize_filename(title)
                filename = f"{safe_title}.mp4"

                logger.info(f"✅ Successfully downloaded: {title} ({len(video_bytes) / (1024*1024):.2f} MB)")

                return video_bytes, filename, metadata

        except Exception as e:
            msg = str(e)
            logger.error(f"❌ Failed to download YouTube video: {msg}")
            # YouTube bot-check signatures → give the admin an actionable hint.
            botcheck = any(
                s in msg
                for s in ("Forbidden", "page needs to be reloaded", "Sign in to confirm", "PO Token", "not a bot")
            )
            if botcheck and not (os.getenv("YOUTUBE_COOKIES_FILE") or os.getenv("YOUTUBE_COOKIES_FROM_BROWSER")):
                raise Exception(
                    "YouTube blocked this download (bot check). Provide YouTube cookies to "
                    "authenticate: export them from a logged-in browser to a cookies.txt and set "
                    "YOUTUBE_COOKIES_FILE on the backend."
                )
            raise Exception(f"Failed to download YouTube video: {msg}")

        finally:
            # Cleanup temp directory
            try:
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp directory: {str(e)}")

    def get_metadata(self, youtube_url: str) -> dict:
        """Fetch metadata only (no download). Often works even when the video
        download is blocked, since it hits a different endpoint. Returns {} on
        any failure (callers treat metadata as best-effort)."""
        try:
            opts = {
                **self.ydl_opts,
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
            }
            cookies_file = os.getenv("YOUTUBE_COOKIES_FILE")
            cookies_browser = os.getenv("YOUTUBE_COOKIES_FROM_BROWSER")
            if cookies_file and os.path.exists(cookies_file):
                opts['cookiefile'] = cookies_file
            elif cookies_browser:
                opts['cookiesfrombrowser'] = (cookies_browser,)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
            return {
                "video_id": info.get("id"),
                "title": info.get("title"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "upload_date": info.get("upload_date"),
                "description": info.get("description"),
            }
        except Exception as e:
            logger.info(f"[yt] metadata fetch failed (non-fatal): {str(e)[:120]}")
            return {}

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename for safe storage

        Args:
            filename: Original filename

        Returns:
            Sanitized filename
        """
        # Remove or replace unsafe characters
        unsafe_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|', '\n', '\r', '\t']
        safe_name = filename

        for char in unsafe_chars:
            safe_name = safe_name.replace(char, '_')

        # Limit length
        max_length = 200
        if len(safe_name) > max_length:
            safe_name = safe_name[:max_length]

        return safe_name.strip()

    def validate_youtube_url(self, url: str) -> bool:
        """
        Validate if URL is a valid YouTube URL

        Args:
            url: URL to validate

        Returns:
            True if valid YouTube URL
        """
        youtube_domains = [
            'youtube.com',
            'www.youtube.com',
            'youtu.be',
            'm.youtube.com',
        ]

        url_lower = url.lower()
        return any(domain in url_lower for domain in youtube_domains)


# Singleton instance
_youtube_downloader: Optional[YouTubeDownloader] = None


def get_youtube_downloader() -> YouTubeDownloader:
    """Get or create YouTube downloader singleton"""
    global _youtube_downloader
    if _youtube_downloader is None:
        _youtube_downloader = YouTubeDownloader()
    return _youtube_downloader
