"""
YouTube Video Downloader Script
Downloads YouTube videos using yt-dlp

Usage:
    uv run python download_youtube.py <youtube_url>
    uv run python download_youtube.py <youtube_url> --output /path/to/save
    uv run python download_youtube.py <youtube_url> --audio-only

Examples:
    uv run python download_youtube.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    uv run python download_youtube.py "https://youtu.be/dQw4w9WgXcQ" --output ~/Downloads
    uv run python download_youtube.py "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --audio-only
"""

import sys
import argparse
from pathlib import Path


def download_youtube_video(url: str, output_path: str = ".", audio_only: bool = False):
    """
    Download YouTube video using yt-dlp

    Args:
        url: YouTube video URL
        output_path: Directory to save the downloaded video
        audio_only: If True, download only audio
    """
    try:
        import yt_dlp
    except ImportError:
        print("❌ yt-dlp not installed!")
        print("\nInstall it with: pip install yt-dlp")
        print("Or with uv: uv pip install yt-dlp")
        sys.exit(1)

    # Create output directory if it doesn't exist
    output_dir = Path(output_path).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"📥 Downloading from: {url}")
    print(f"💾 Saving to: {output_dir}")
    print()

    # Configure yt-dlp options
    ydl_opts = {
        'outtmpl': str(output_dir / '%(title)s.%(ext)s'),
        'progress_hooks': [progress_hook],
    }

    if audio_only:
        print("🎵 Audio-only mode enabled")
        ydl_opts.update({
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        })
    else:
        print("🎬 Downloading video with best quality")
        ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get video info first
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            duration = info.get('duration', 0)

            print(f"📹 Title: {title}")
            if duration:
                mins, secs = divmod(duration, 60)
                print(f"⏱️  Duration: {int(mins)}:{int(secs):02d}")
            print()

            # Download the video
            ydl.download([url])

            print()
            print("✅ Download completed successfully!")
            print(f"📁 Saved to: {output_dir}")

    except Exception as e:
        print(f"\n❌ Error downloading video: {str(e)}")
        sys.exit(1)


def progress_hook(d):
    """Progress callback for yt-dlp"""
    if d['status'] == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
        downloaded = d.get('downloaded_bytes', 0)
        speed = d.get('speed', 0)
        eta = d.get('eta', 0)

        if total > 0:
            percent = (downloaded / total) * 100
            downloaded_mb = downloaded / 1024 / 1024
            total_mb = total / 1024 / 1024
            speed_mb = speed / 1024 / 1024 if speed else 0

            # Print progress bar
            bar_length = 40
            filled = int(bar_length * downloaded / total)
            bar = '█' * filled + '░' * (bar_length - filled)

            print(f"\r⬇️  {bar} {percent:.1f}% | {downloaded_mb:.1f}/{total_mb:.1f} MB | {speed_mb:.1f} MB/s | ETA: {eta}s", end='', flush=True)

    elif d['status'] == 'finished':
        print("\n🔄 Processing file...")


def main():
    parser = argparse.ArgumentParser(
        description='Download YouTube videos using yt-dlp',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  %(prog)s "https://youtu.be/dQw4w9WgXcQ" --output ~/Downloads
  %(prog)s "https://www.youtube.com/watch?v=dQw4w9WgXcQ" --audio-only
        """
    )

    parser.add_argument('url', help='YouTube video URL')
    parser.add_argument('-o', '--output', default='.', help='Output directory (default: current directory)')
    parser.add_argument('-a', '--audio-only', action='store_true', help='Download audio only (converts to MP3)')

    args = parser.parse_args()

    # Validate URL
    if not ('youtube.com' in args.url or 'youtu.be' in args.url):
        print("❌ Invalid YouTube URL!")
        print("Please provide a valid YouTube URL (youtube.com or youtu.be)")
        sys.exit(1)

    download_youtube_video(args.url, args.output, args.audio_only)


if __name__ == "__main__":
    main()
