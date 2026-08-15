"""
Video Scene Detector Client
Uses PySceneDetect for fast, optimized scene detection
Thread-safe singleton implementation
"""

import tempfile
import threading
from typing import List, Dict, Optional
from pathlib import Path
import numpy as np
from scenedetect import detect, ContentDetector, AdaptiveDetector
from app.logger import logger
from app.settings import settings


class VideoSceneDetector:
    """Thread-safe video scene detector using PySceneDetect"""

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
        """Initialize scene detector"""
        if not hasattr(self, '_initialized'):
            self._initialized = True
            logger.info("✅ Video scene detector initialized (PySceneDetect)")

    def detect_scenes_from_video(
        self,
        file_content: bytes,
        filename: str,
        threshold: Optional[float] = None,
        downscale: int = 2
    ) -> tuple[List[Dict], Dict[int, float]]:
        """Legacy wrapper — writes temp file then delegates to detect_scenes_from_path."""
        extension = Path(filename).suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
            tmp_file.write(file_content)
            tmp_file.flush()
            tmp_file_path = tmp_file.name
        try:
            return self.detect_scenes_from_path(tmp_file_path, threshold, downscale)
        finally:
            import os
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)

    def detect_scenes_from_path(
        self,
        video_path: str,
        threshold: Optional[float] = None,
        downscale: int = 2
    ) -> tuple[List[Dict], Dict[int, float]]:
        """
        Detect scenes using PySceneDetect from an existing file path.

        Args:
            video_path: Path to the video file on disk
            threshold: Scene detection threshold (default: 18.0)
            downscale: Downscale factor for speed (1=full res, 2=half res)

        Returns:
            Tuple of (scenes, entropy_cache)
        """
        try:
            threshold = threshold or 18.0
            logger.info(
                f"🔍 PySceneDetect: Detecting scenes "
                f"(threshold={threshold}, downscale={downscale}x)"
            )

            from scenedetect.video_manager import VideoManager
            from scenedetect.scene_manager import SceneManager

            video_manager = VideoManager([video_path])
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=threshold))
            video_manager.set_downscale_factor(downscale)
            video_manager.start()
            scene_manager.detect_scenes(video_manager, show_progress=False)
            scene_list = scene_manager.get_scene_list()
            video_manager.release()

            logger.info(f"✅ PySceneDetect found {len(scene_list)} scenes")

            scenes = []
            for i, (start_time, end_time) in enumerate(scene_list):
                scenes.append({
                    'scene_id': i,
                    'start_frame': start_time.get_frames(),
                    'end_frame': end_time.get_frames(),
                    'start_time': start_time.get_seconds(),
                    'end_time': end_time.get_seconds(),
                    'num_frames': end_time.get_frames() - start_time.get_frames()
                })

            entropy_cache = {}
            logger.info(
                f"✅ Scene detection complete: {len(scenes)} scenes detected "
                f"(PySceneDetect with {downscale}x downscale)"
            )
            return scenes, entropy_cache

        except Exception as e:
            logger.error(f"❌ PySceneDetect scene detection failed: {str(e)}")
            raise Exception(f"Scene detection failed: {str(e)}")

    def select_key_frames_from_video(
        self,
        file_content: bytes,
        filename: str,
        scenes: List[Dict]
    ) -> List[Dict]:
        """Legacy wrapper — writes temp file then delegates to select_key_frames_from_path."""
        extension = Path(filename).suffix.lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp_file:
            tmp_file.write(file_content)
            tmp_file.flush()
            tmp_file_path = tmp_file.name
        try:
            return self.select_key_frames_from_path(tmp_file_path, scenes)
        finally:
            import os
            if os.path.exists(tmp_file_path):
                os.unlink(tmp_file_path)

    def select_key_frames_from_path(
        self,
        video_path: str,
        scenes: List[Dict]
    ) -> List[Dict]:
        """
        Select key frames using entropy from an existing file path.

        Args:
            video_path: Path to the video file on disk
            scenes: List of scene dicts from detect_scenes

        Returns:
            List of key frame dictionaries
        """
        try:
            logger.info(f"🔑 Selecting key frames from {len(scenes)} scenes")

            import cv2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                raise Exception(f"Failed to open video: {video_path}")

            key_frames = []

            for scene in scenes:
                middle_frame_num = (scene['start_frame'] + scene['end_frame']) // 2
                cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame_num)
                ret, frame = cap.read()

                if ret:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    entropy = self._calculate_entropy(gray)

                    scene_duration = scene['end_time'] - scene['start_time']
                    scene_frames = scene['end_frame'] - scene['start_frame']
                    frame_offset = middle_frame_num - scene['start_frame']

                    if scene_frames > 0:
                        timestamp = scene['start_time'] + (frame_offset / scene_frames) * scene_duration
                    else:
                        timestamp = scene['start_time']

                    key_frames.append({
                        'frame_number': middle_frame_num,
                        'timestamp': timestamp,
                        'scene_id': scene['scene_id'],
                        'scene_start': scene['start_time'],
                        'scene_end': scene['end_time'],
                        'entropy': entropy
                    })
                else:
                    logger.warning(f"⚠️ Could not extract frame for scene {scene['scene_id']}")

            cap.release()

            logger.info(f"✅ Selected {len(key_frames)} key frames")
            return key_frames

        except Exception as e:
            logger.error(f"❌ Key frame selection failed: {str(e)}")
            raise Exception(f"Key frame selection failed: {str(e)}")

    def select_key_frames_from_cache(
        self,
        scenes: List[Dict],
        entropy_cache: Dict[int, float]
    ) -> List[Dict]:
        """
        Select key frames from cached entropy values (backward compatibility)

        Since PySceneDetect doesn't cache entropy, this method now
        returns middle frames with 0 entropy as fallback.

        Args:
            scenes: List of scene dicts
            entropy_cache: Dict mapping frame_number → entropy value (ignored)

        Returns:
            List of key frame dictionaries
        """
        logger.info(f"🔑 Selecting key frames (using middle frames as fallback)")

        key_frames = []
        for scene in scenes:
            # Use middle frame
            middle_frame_num = (scene['start_frame'] + scene['end_frame']) // 2

            # Calculate timestamp
            scene_duration = scene['end_time'] - scene['start_time']
            scene_frames = scene['end_frame'] - scene['start_frame']
            frame_offset = middle_frame_num - scene['start_frame']

            if scene_frames > 0:
                timestamp = scene['start_time'] + (frame_offset / scene_frames) * scene_duration
            else:
                timestamp = scene['start_time']

            key_frames.append({
                'frame_number': middle_frame_num,
                'timestamp': timestamp,
                'scene_id': scene['scene_id'],
                'scene_start': scene['start_time'],
                'scene_end': scene['end_time'],
                'entropy': 0.0  # Unknown entropy
            })

        logger.info(f"✅ Selected {len(key_frames)} key frames")
        return key_frames

    def _calculate_entropy(self, image: np.ndarray) -> float:
        """
        Calculate Shannon entropy of an image

        Entropy = -sum(p * log2(p)) where p is histogram probabilities

        Args:
            image: Grayscale image as numpy array

        Returns:
            Entropy value (higher = more information)
        """
        # Calculate histogram
        histogram, _ = np.histogram(image.flatten(), bins=256, range=(0, 256))

        # Normalize to probabilities
        histogram = histogram / histogram.sum()

        # Remove zero probabilities (log(0) is undefined)
        histogram = histogram[histogram > 0]

        # Calculate entropy
        entropy = -np.sum(histogram * np.log2(histogram))

        return float(entropy)


# Singleton instance
_video_scene_detector: Optional[VideoSceneDetector] = None
_client_lock = threading.Lock()


def get_video_scene_detector() -> VideoSceneDetector:
    """
    Get or create thread-safe VideoSceneDetector singleton instance

    Returns:
        VideoSceneDetector: Singleton client instance
    """
    global _video_scene_detector

    if _video_scene_detector is None:
        with _client_lock:
            if _video_scene_detector is None:
                _video_scene_detector = VideoSceneDetector()

    return _video_scene_detector
