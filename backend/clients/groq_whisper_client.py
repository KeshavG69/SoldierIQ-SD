"""
Groq Whisper Client for audio transcription
Thread-safe implementation using Whisper Large V3
Supports large files via chunking (max 25MB per API call)
"""

import tempfile
import threading
from typing import Optional
from pathlib import Path
from groq import Groq
from pydub import AudioSegment
from app.logger import logger
from app.settings import settings


class GroqWhisperClient:
    """Thread-safe Groq Whisper client for audio transcription"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern with thread locking"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize Groq client for Whisper"""
        if not hasattr(self, '_initialized'):
            self.api_key = settings.GROQ_API_KEY

            if not self.api_key:
                raise ValueError("GROQ_API_KEY not configured in settings")

            # Initialize Groq client
            self.client = Groq(api_key=self.api_key)
            self._initialized = True
            logger.info("✅ Groq Whisper client initialized")

    def transcribe_audio(self, file_content: bytes, filename: str) -> str:
        """
        Transcribe audio file using Groq's Whisper Large V3

        Args:
            file_content: Audio file content as bytes
            filename: Original filename

        Returns:
            Transcribed text (plain text, no timestamps)

        Raises:
            Exception: If transcription fails
        """
        segments = self.transcribe_audio_with_timestamps(file_content, filename)
        # Combine all segment texts
        return " ".join([seg['text'] for seg in segments])

    def transcribe_audio_with_timestamps(self, file_content: bytes, filename: str) -> list:
        """
        Transcribe audio file with timestamps using Groq's Whisper Large V3
        Automatically chunks large files (>20MB) to respect API limits

        Args:
            file_content: Audio file content as bytes
            filename: Original filename

        Returns:
            List of segments with timestamps:
            [{'start': float, 'end': float, 'text': str}, ...]

        Raises:
            Exception: If transcription fails
        """
        try:
            extension = Path(filename).suffix.lower()
            file_size_mb = len(file_content) / (1024 * 1024)

            logger.info(f"🎵 Audio file size: {file_size_mb:.2f} MB")

            # If file is small enough, process directly
            if file_size_mb <= 20:
                return self._transcribe_single_file(file_content, filename)

            # For large files, chunk and process in parallel
            logger.info(f"📦 File too large ({file_size_mb:.2f} MB), chunking into smaller segments...")
            return self._transcribe_chunked_file(file_content, filename)

        except Exception as e:
            logger.error(f"❌ Groq Whisper transcription failed for {filename}: {str(e)}")
            raise Exception(f"Audio transcription failed: {str(e)}")

    def _transcribe_single_file(self, file_content: bytes, filename: str) -> list:
        """Transcribe a single audio file without chunking"""
        extension = Path(filename).suffix.lower()

        # Write to temp file (Groq API requires file-like object)
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=extension
        ) as tmp_file:
            tmp_file.write(file_content)
            tmp_file.flush()
            tmp_file_path = tmp_file.name

        try:
            # Transcribe using Groq Whisper Large V3 with verbose JSON for timestamps
            with open(tmp_file_path, "rb") as audio_file:
                transcription = self.client.audio.transcriptions.create(
                    file=(filename, audio_file.read()),
                    model="whisper-large-v3",
                    response_format="verbose_json",  # Get timestamps
                    language="en",  # Optional: specify language or let it auto-detect
                    temperature=0.0
                )

            # Extract segments with timestamps
            segments = []
            if hasattr(transcription, 'segments') and transcription.segments:
                for seg in transcription.segments:
                    # Handle both dict and object access patterns
                    if isinstance(seg, dict):
                        segments.append({
                            'start': seg['start'],
                            'end': seg['end'],
                            'text': seg['text'].strip()
                        })
                    else:
                        segments.append({
                            'start': seg.start,
                            'end': seg.end,
                            'text': seg.text.strip()
                        })
            else:
                # Fallback if no segments (shouldn't happen with verbose_json)
                logger.warning(f"No segments returned for {filename}, using full text")
                text = transcription.text if hasattr(transcription, 'text') else str(transcription)
                segments = [{'start': 0.0, 'end': 0.0, 'text': text}]

            logger.info(f"✅ Groq Whisper transcribed {len(segments)} segments from {filename}")
            return segments

        finally:
            # Clean up temp file
            import os
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)

    def _transcribe_chunked_file(self, file_content: bytes, filename: str) -> list:
        """
        Transcribe large audio file by splitting into chunks
        Each chunk is max 10 minutes to stay under 20MB limit
        """
        import os

        extension = Path(filename).suffix.lower()

        # Write original file to temp location
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
            tmp_file.write(file_content)
            tmp_file_path = tmp_file.name

        try:
            # Load audio with pydub
            logger.info(f"📂 Loading audio file...")
            audio = AudioSegment.from_file(tmp_file_path)

            # Calculate chunk size (10 minutes = 600,000 milliseconds)
            chunk_duration_ms = 10 * 60 * 1000  # 10 minutes
            total_duration_ms = len(audio)
            total_duration_min = total_duration_ms / 60000

            logger.info(f"⏱️  Total duration: {total_duration_min:.1f} minutes")

            # Split audio into chunks
            chunks = []
            for start_ms in range(0, total_duration_ms, chunk_duration_ms):
                end_ms = min(start_ms + chunk_duration_ms, total_duration_ms)
                chunk = audio[start_ms:end_ms]
                chunks.append({
                    'audio': chunk,
                    'start_time': start_ms / 1000.0,  # Convert to seconds
                    'end_time': end_ms / 1000.0
                })

            logger.info(f"✂️  Split into {len(chunks)} chunks")

            # Transcribe chunks in parallel (up to 3 concurrent)
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def transcribe_one_chunk(i, chunk_data):
                """Transcribe a single audio chunk and return offset-adjusted segments."""
                logger.info(f"🎤 Transcribing chunk {i}/{len(chunks)} ({chunk_data['start_time']:.1f}s - {chunk_data['end_time']:.1f}s)...")

                with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as chunk_file:
                    chunk_data['audio'].export(chunk_file.name, format='mp3')
                    chunk_path = chunk_file.name

                try:
                    with open(chunk_path, 'rb') as f:
                        chunk_content = f.read()

                    chunk_segments = self._transcribe_single_file(
                        chunk_content,
                        f"{Path(filename).stem}_chunk{i}.mp3"
                    )

                    time_offset = chunk_data['start_time']
                    for seg in chunk_segments:
                        seg['start'] += time_offset
                        seg['end'] += time_offset

                    return i, chunk_segments
                finally:
                    if os.path.exists(chunk_path):
                        os.unlink(chunk_path)

            # Run up to 3 transcriptions concurrently
            results = {}
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {
                    executor.submit(transcribe_one_chunk, i, chunk_data): i
                    for i, chunk_data in enumerate(chunks, 1)
                }
                for future in as_completed(futures):
                    idx, segs = future.result()
                    results[idx] = segs

            # Reassemble in order
            all_segments = []
            for i in sorted(results.keys()):
                all_segments.extend(results[i])

            logger.info(f"✅ Chunked transcription complete (parallel): {len(all_segments)} total segments")
            return all_segments

        finally:
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)

    @staticmethod
    def is_supported(extension: str) -> bool:
        """
        Check if file extension is supported for audio transcription

        Args:
            extension: File extension with dot (e.g., '.mp3')

        Returns:
            True if supported
        """
        # Groq Whisper supports common audio formats
        supported_formats = [
            ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a",
            ".wav", ".webm", ".flac", ".ogg", ".aac"
        ]
        return extension.lower() in supported_formats


# Singleton instance
_groq_whisper_client: Optional[GroqWhisperClient] = None
_client_lock = threading.Lock()


def get_groq_whisper_client() -> GroqWhisperClient:
    """
    Get or create thread-safe GroqWhisperClient singleton instance

    Returns:
        GroqWhisperClient: Singleton client instance
    """
    global _groq_whisper_client

    if _groq_whisper_client is None:
        with _client_lock:
            if _groq_whisper_client is None:
                _groq_whisper_client = GroqWhisperClient()

    return _groq_whisper_client
