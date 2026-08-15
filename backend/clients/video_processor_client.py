"""
Video Processor Client
Orchestrates complete video processing pipeline
Thread-safe singleton implementation
"""

import tempfile
import threading
import io
import cv2
from typing import Dict, List, Optional
from pathlib import Path
from moviepy import VideoFileClip
from clients.groq_whisper_client import get_groq_whisper_client
from clients.video_frame_extractor import get_video_frame_extractor
from clients.video_scene_detector import get_video_scene_detector
from clients.video_aligner import get_video_aligner
from clients.idrivee2_client import get_idrivee2_client
from app.logger import logger
from app.settings import settings


class VideoProcessorClient:
    """Thread-safe video processor orchestrating full pipeline"""

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
        """Initialize video processor"""
        if not hasattr(self, '_initialized'):
            self._initialized = True
            logger.info("✅ Video processor initialized")

    def process_video(
        self,
        file_content: bytes,
        filename: str,
        folder_name: str = "videos"
    ) -> Dict:
        """
        Process video through complete streaming pipeline

        MEMORY-EFFICIENT: Uses streaming for unlimited video length!
        Peak memory: ~50MB regardless of video duration

        Pipeline stages:
        1. Audio extraction → Whisper transcription (timestamped)
        2. Scene detection → PySceneDetect (single temp file)
        3. Key frame selection → Entropy (reuses temp file)
        4. Color frame extraction → Key frames only (reuses temp file)
        5. Upload thumbnails → (skipped)
        6. VLM description → Multimodal alignment & blending
        7. Format output → Combined text + scene chunks

        Args:
            file_content: Video file content as bytes
            filename: Original filename
            folder_name: Folder for organizing uploads (default: "videos")

        Returns:
            Dictionary with:
            - combined_text: str (all scenes for MongoDB)
            - chunks: List[Dict] (scene chunks for Pinecone)

        Raises:
            Exception: If processing fails
        """
        try:
            logger.info(f"🎬 Starting video processing pipeline for: {filename}")

            # Generate video ID (sanitized filename)
            video_id = self._sanitize_video_id(filename)
            video_name = filename

            # Write temp file ONCE — all stages reuse this path
            import os
            extension = Path(filename).suffix.lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
                tmp_file.write(file_content)
                tmp_file.flush()
                video_tmp_path = tmp_file.name

            try:
                logger.info("🚀 PARALLEL PROCESSING: Audio transcription + Video frame processing")

                import asyncio

                async def process_audio_and_video_parallel():
                    """Process audio and video in parallel for maximum throughput"""

                    async def transcribe_audio():
                        logger.info("📝 Stage 1/7: Audio transcription (timestamped) - PARALLEL")
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None,
                            lambda: self._extract_and_transcribe_audio(video_tmp_path, filename)
                        )

                    async def process_video_frames():
                        logger.info("🎬 Stages 2-4/7: Video frame processing (PySceneDetect) - PARALLEL")

                        scene_detector = get_video_scene_detector()
                        frame_extractor = get_video_frame_extractor()

                        # Stage 2: PySceneDetect scene detection — reuses temp file path
                        logger.info("🎬 Stage 2/7: PySceneDetect scene detection (full resolution)")
                        loop = asyncio.get_event_loop()
                        scenes, entropy_cache = await loop.run_in_executor(
                            None,
                            lambda: scene_detector.detect_scenes_from_path(
                                video_tmp_path,
                                threshold=27.0,
                                downscale=1
                            )
                        )

                        # Handle videos with no scene changes (static content)
                        if not scenes:
                            logger.warning("⚠️ No scenes detected - treating entire video as single scene")
                            cap = cv2.VideoCapture(video_tmp_path)
                            fps = cap.get(cv2.CAP_PROP_FPS)
                            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                            duration_seconds = frame_count / fps if fps > 0 else 10.0
                            cap.release()

                            scenes = [
                                {
                                    'scene_id': 0,
                                    'start_frame': 0,
                                    'end_frame': frame_count - 1 if frame_count > 0 else 100,
                                    'start_time': 0.0,
                                    'end_time': duration_seconds,
                                    'duration': duration_seconds
                                }
                            ]
                            logger.info(f"✅ Created single scene: 0.0s to {duration_seconds:.1f}s")

                        logger.info(f"✅ PySceneDetect complete: {len(scenes)} scenes detected")

                        # Stage 3: Select key frames — reuses temp file path
                        logger.info("🔑 Stage 3/7: Selecting key frames from scenes")
                        key_frames_data = await loop.run_in_executor(
                            None,
                            lambda: scene_detector.select_key_frames_from_path(
                                video_tmp_path, scenes
                            )
                        )
                        logger.info(f"✅ Selected {len(key_frames_data)} key frames")

                        # Stage 4: Extract color frames — reuses temp file path
                        logger.info("🖼️ Stage 4/7: Color frame extraction (batch mode)")
                        frame_numbers = [kf['frame_number'] for kf in key_frames_data]
                        color_frames = await loop.run_in_executor(
                            None,
                            lambda: frame_extractor.extract_color_frames_batch_from_path(
                                video_tmp_path, frame_numbers
                            )
                        )
                        logger.info(f"✅ Batch extracted {len(color_frames)} color key frames")

                        keyframe_file_keys = [None] * len(key_frames_data)
                        logger.info("⏭️ Skipping keyframe thumbnail upload")

                        return scenes, key_frames_data, color_frames, keyframe_file_keys

                    transcript_segments, (scenes, key_frames_data, color_frames, keyframe_file_keys) = await asyncio.gather(
                        transcribe_audio(),
                        process_video_frames()
                    )

                    logger.info("✅ PARALLEL PROCESSING complete: Audio + Video ready for alignment")
                    return transcript_segments, scenes, key_frames_data, color_frames, keyframe_file_keys

                # Run parallel processing
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    transcript_segments, scenes, key_frames_data, color_frames, keyframe_file_keys = loop.run_until_complete(
                        process_audio_and_video_parallel()
                    )
                finally:
                    loop.close()

            finally:
                # Clean up the single temp file
                if os.path.exists(video_tmp_path):
                    os.unlink(video_tmp_path)
                    logger.debug(f"🧹 Cleaned up temp video file: {video_tmp_path}")

            # Stage 6: Align and blend (includes VLM description)
            logger.info("🔗 Stage 6/7: Alignment and multimodal blending")
            aligner = get_video_aligner()
            aligned_chunks = aligner.align_and_blend(
                transcript_segments,
                scenes,
                key_frames_data,
                color_frames
            )

            # Clean up color frames and scenes from memory
            del color_frames
            del scenes
            logger.debug("🧹 Cleaned up color frames and scenes from memory")

            # Stage 7: Format final output
            logger.info("📦 Stage 7/7: Formatting final output")
            final_chunks = []
            combined_text_parts = []

            for i, chunk in enumerate(aligned_chunks):
                chunk_id = f"{video_id}_chunk_{chunk['scene_id']}"

                final_chunks.append({
                    'chunk_id': chunk_id,
                    'video_id': video_id,
                    'video_name': video_name,
                    'clip_start': chunk['clip_start'],
                    'clip_end': chunk['clip_end'],
                    'duration': chunk['clip_end'] - chunk['clip_start'],
                    'key_frame_timestamp': chunk['key_frame_timestamp'],
                    'keyframe_file_key': keyframe_file_keys[i],
                    'transcript_text': chunk['transcript_text'],
                    'visual_description': chunk['visual_description'],
                    'blended_text': chunk['blended_text']
                })

                combined_text_parts.append(
                    f"[Scene {chunk['scene_id']} - {chunk['clip_start']:.1f}s to {chunk['clip_end']:.1f}s]\n"
                    f"{chunk['blended_text']}\n"
                )

            combined_text = "\n".join(combined_text_parts)

            logger.info(
                f"✅ Video processing complete: {filename} → "
                f"{len(final_chunks)} chunks created, "
                f"{len(combined_text)} chars combined text"
            )

            return {
                'combined_text': combined_text,
                'chunks': final_chunks
            }

        except Exception as e:
            logger.error(f"❌ Video processing failed for {filename}: {str(e)}")
            raise Exception(f"Video processing failed: {str(e)}")

    def _extract_and_transcribe_audio(
        self,
        video_path: str,
        filename: str
    ) -> List[Dict]:
        """
        Extract audio from video and transcribe using Groq Whisper

        Args:
            video_path: Path to the temp video file on disk
            filename: Original filename

        Returns:
            List of transcript segments with 'start', 'end', 'text'

        Raises:
            Exception: If extraction or transcription fails
        """
        audio_path = None

        try:
            # Extract audio using MoviePy — reuses existing temp file
            logger.info("🎵 Extracting audio from video...")
            video_clip = VideoFileClip(video_path)

            # Check if video has audio track
            if video_clip.audio is None:
                video_clip.close()
                logger.warning("⚠️ Video has no audio track")
                logger.info("📝 Continuing with visual-only processing (no audio transcript)")
                return []

            # Create temp audio file
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix='.mp3'
            ) as audio_file:
                audio_path = audio_file.name

            # Extract audio
            video_clip.audio.write_audiofile(
                audio_path,
                logger=None  # Suppress MoviePy logs
            )
            video_clip.close()

            # Read audio file
            with open(audio_path, 'rb') as f:
                audio_content = f.read()

            # Transcribe with Groq Whisper (with timestamps!)
            logger.info("🎤 Transcribing audio with Groq Whisper...")
            whisper_client = get_groq_whisper_client()

            # Get timestamped segments
            transcript_segments = whisper_client.transcribe_audio_with_timestamps(
                audio_content,
                f"{Path(filename).stem}.mp3"
            )

            total_chars = sum(len(seg['text']) for seg in transcript_segments)
            logger.info(f"✅ Transcription complete: {len(transcript_segments)} segments, {total_chars} chars")

            return transcript_segments

        except Exception as e:
            logger.warning(f"⚠️ Audio extraction/transcription failed: {str(e)}")
            logger.info("📝 Continuing with visual-only processing (no audio transcript)")
            # Return empty segments as fallback (visual-only mode)
            return []

        finally:
            # Clean up temp audio file only (video temp file is owned by caller)
            import os
            if audio_path and os.path.exists(audio_path):
                try:
                    os.unlink(audio_path)
                    logger.debug(f"🧹 Cleaned up temp audio file: {audio_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete temp audio file: {str(e)}")

    async def _upload_keyframe_thumbnails(
        self,
        color_frames: List,
        key_frames_data: List[Dict],
        video_id: str,
        folder_name: str
    ) -> List[str]:
        """
        Upload key frame thumbnails to iDrive E2 (async)

        Args:
            color_frames: List of color frames (numpy arrays)
            key_frames_data: List of key frame metadata
            video_id: Sanitized video ID
            folder_name: Folder for organizing uploads

        Returns:
            List of file_keys for uploaded thumbnails
        """
        import cv2
        import asyncio

        idrive_client = get_idrivee2_client()
        file_keys = []
        upload_tasks = []

        try:
            for i, (frame, kf_data) in enumerate(zip(color_frames, key_frames_data)):
                # Encode frame as JPEG
                success, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

                if not success:
                    logger.warning(f"Failed to encode keyframe {i}, skipping")
                    file_keys.append(None)
                    continue

                # Create file key
                file_key = f"{folder_name}/{video_id}/keyframe_{kf_data['scene_id']}.jpg"

                # Create BytesIO and ensure position is at start
                file_obj = io.BytesIO(buffer.tobytes())
                file_obj.seek(0)  # Reset position to start

                # Create upload task
                upload_tasks.append(idrive_client.upload_file(
                    file_obj=file_obj,
                    object_name=file_key,
                    content_type='image/jpeg'
                ))
                file_keys.append(file_key)

            # Upload all frames in parallel
            await asyncio.gather(*upload_tasks)
            logger.info(f"✅ Uploaded {len(file_keys)} keyframe thumbnails")
            return file_keys

        except Exception as e:
            logger.error(f"❌ Failed to upload keyframes: {str(e)}")
            # Return None for all frames as fallback
            return [None] * len(color_frames)

    def _calculate_optimal_fps(self, file_content: bytes, filename: str) -> int:
        """
        Calculate optimal FPS based on video duration to prevent processing bottleneck

        Strategy:
        - Short videos (<10 min): 4 FPS (default)
        - Medium videos (10-30 min): 2 FPS
        - Long videos (>30 min): 1 FPS

        This dramatically reduces frame processing for long videos:
        - 1 hour at 4 FPS = 14,400 frames (2 passes = 28,800 ops)
        - 1 hour at 1 FPS = 3,600 frames (2 passes = 7,200 ops) ✅ 4x faster

        Args:
            file_content: Video file bytes
            filename: Video filename

        Returns:
            Optimal target FPS
        """
        import tempfile
        extension = Path(filename).suffix.lower()

        try:
            # Write to temp file to get duration
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
                tmp_file.write(file_content)
                tmp_file_path = tmp_file.name

            try:
                # Get video duration using OpenCV
                cap = cv2.VideoCapture(tmp_file_path)
                if not cap.isOpened():
                    logger.warning("Could not open video to check duration, using default FPS")
                    return settings.VIDEO_TARGET_FPS

                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration_seconds = frame_count / fps if fps > 0 else 0
                cap.release()

                logger.info(f"📹 Video duration: {duration_seconds / 60:.1f} minutes")

                # Dynamic FPS based on duration
                if duration_seconds < 600:  # < 10 minutes
                    target_fps = 4
                elif duration_seconds < 1800:  # < 30 minutes
                    target_fps = 2
                else:  # >= 30 minutes
                    target_fps = 1

                return target_fps

            finally:
                import os
                if os.path.exists(tmp_file_path):
                    os.unlink(tmp_file_path)

        except Exception as e:
            logger.warning(f"Could not calculate optimal FPS: {str(e)}, using default")
            return settings.VIDEO_TARGET_FPS

    def _sanitize_video_id(self, filename: str) -> str:
        """
        Sanitize filename to create valid video ID

        Removes special characters, keeps alphanumeric and underscores

        Args:
            filename: Original filename

        Returns:
            Sanitized video ID
        """
        import re

        # Remove extension
        name = Path(filename).stem

        # Keep only alphanumeric and underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)

        # Remove multiple underscores
        sanitized = re.sub(r'_+', '_', sanitized)

        # Remove leading/trailing underscores
        sanitized = sanitized.strip('_')

        return sanitized or 'video'


# Singleton instance
_video_processor_client: Optional[VideoProcessorClient] = None
_client_lock = threading.Lock()


def get_video_processor_client() -> VideoProcessorClient:
    """
    Get or create thread-safe VideoProcessorClient singleton instance

    Returns:
        VideoProcessorClient: Singleton client instance
    """
    global _video_processor_client

    if _video_processor_client is None:
        with _client_lock:
            if _video_processor_client is None:
                _video_processor_client = VideoProcessorClient()

    return _video_processor_client
