"""
Video Aligner Client
Aligns transcript segments with visual scenes and blends multimodal content
Thread-safe singleton implementation
"""

import base64
import bisect
import cv2
import threading
import asyncio
from typing import List, Dict, Optional
import numpy as np
from langchain_core.prompts import ChatPromptTemplate
from clients.ultimate_llm import get_llm
from app.logger import logger

# SSIM threshold: if two adjacent keyframes are this similar, reuse VLM description
VLM_DEDUP_SSIM_THRESHOLD = 0.92


class VideoAligner:
    """Thread-safe video aligner for multimodal content blending"""

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
        """Initialize video aligner"""
        if not hasattr(self, '_initialized'):
            self._initialized = True
            logger.info("✅ Video aligner initialized")

    def align_and_blend(
        self,
        transcript_segments: List[Dict],
        scenes: List[Dict],
        key_frames_data: List[Dict],
        color_frames: List[np.ndarray]
    ) -> List[Dict]:
        """
        Align transcript with scenes and blend with visual descriptions

        Args:
            transcript_segments: List of dicts with 'start', 'end', 'text'
            scenes: List of scene dicts from scene detector
            key_frames_data: List of key frame metadata
            color_frames: List of color frames (BGR) corresponding to key_frames_data

        Returns:
            List of aligned chunks with:
            - scene_id: int
            - clip_start: float
            - clip_end: float
            - transcript_text: str
            - visual_description: str
            - blended_text: str
            - key_frame_timestamp: float

        Raises:
            Exception: If alignment/blending fails
        """
        try:
            logger.info(
                f"🔗 Aligning {len(transcript_segments)} transcript segments "
                f"with {len(scenes)} scenes (parallel with max 25 concurrent)"
            )

            # Validate that all lists have matching lengths
            if len(scenes) != len(key_frames_data) or len(scenes) != len(color_frames):
                logger.error(
                    f"❌ Mismatch in data lengths: {len(scenes)} scenes, "
                    f"{len(key_frames_data)} key_frames, {len(color_frames)} color_frames"
                )
                raise ValueError(
                    f"Data length mismatch: scenes={len(scenes)}, "
                    f"key_frames={len(key_frames_data)}, frames={len(color_frames)}"
                )

            if len(scenes) == 0:
                logger.warning("⚠️ No scenes detected in video")
                return []

            # Process all scenes in parallel with semaphore limit
            aligned_chunks = self._process_scenes_parallel(
                scenes,
                transcript_segments,
                key_frames_data,
                color_frames
            )

            logger.info(f"✅ Created {len(aligned_chunks)} aligned chunks")

            return aligned_chunks

        except Exception as e:
            logger.error(f"❌ Alignment and blending failed: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Alignment and blending failed: {str(e)}")

    def _process_scenes_parallel(
        self,
        scenes: List[Dict],
        transcript_segments: List[Dict],
        key_frames_data: List[Dict],
        color_frames: List
    ) -> List[Dict]:
        """
        Process all scenes with BATCHED parallelism for maximum throughput

        Strategy (for 916 scenes):
        Phase 1: Batch all 916 VLM descriptions together (25 concurrent)
        Phase 2: Batch all 916 blending calls together (25 concurrent)

        Performance:
        - Old approach: 916 scenes / 5 = 183 batches × 15s = ~45 minutes
        - New approach: 916 / 25 = 37 batches × 2 phases × 7s = ~9 minutes ✅

        Args:
            scenes: List of scene dicts
            transcript_segments: List of transcript segments
            key_frames_data: List of key frame metadata
            color_frames: List of color frames

        Returns:
            List of aligned chunks (same order as scenes)
        """
        async def process_all_batched():
            """Process with batched API calls for maximum throughput"""
            num_scenes = len(scenes)

            # Step 1: Prepare all transcript texts (no API calls, fast)
            logger.info(f"📝 Step 1/3: Preparing {num_scenes} transcript alignments...")
            transcript_texts = []
            for scene in scenes:
                overlapping_segments = self._find_overlapping_segments(
                    transcript_segments,
                    scene['start_time'],
                    scene['end_time']
                )
                transcript_text = " ".join([seg['text'] for seg in overlapping_segments])
                transcript_texts.append(transcript_text)
            logger.info(f"✅ Prepared {num_scenes} transcript texts")

            # Step 2: Batch VLM descriptions — skip visually similar adjacent frames
            logger.info(f"🎨 Step 2/3: Processing VLM descriptions (dedup + 25 concurrent)...")
            semaphore_vlm = asyncio.Semaphore(25)

            # Pre-compute which frames need VLM vs. can reuse previous
            needs_vlm = [True] * num_scenes  # first frame always needs VLM
            reuse_from = [None] * num_scenes
            skipped = 0
            for i in range(1, num_scenes):
                ssim = self._compute_ssim(color_frames[i - 1], color_frames[i])
                if ssim >= VLM_DEDUP_SSIM_THRESHOLD:
                    needs_vlm[i] = False
                    # Find the original frame this chain reuses from
                    reuse_from[i] = reuse_from[i - 1] if reuse_from[i - 1] is not None else i - 1
                    skipped += 1

            if skipped > 0:
                logger.info(f"⏭️ Skipping VLM for {skipped}/{num_scenes} visually similar frames (SSIM >= {VLM_DEDUP_SSIM_THRESHOLD})")

            async def describe_one_frame(i: int):
                async with semaphore_vlm:
                    return await self._describe_frame_with_vlm_async(
                        color_frames[i],
                        key_frames_data[i]['timestamp']
                    )

            # Only call VLM for unique frames
            vlm_tasks = {}
            for i in range(num_scenes):
                if needs_vlm[i]:
                    vlm_tasks[i] = describe_one_frame(i)

            vlm_results = {}
            if vlm_tasks:
                indices = list(vlm_tasks.keys())
                results = await asyncio.gather(*vlm_tasks.values())
                for idx, result in zip(indices, results):
                    vlm_results[idx] = result

            # Build full visual_descriptions array, reusing where needed
            visual_descriptions = []
            for i in range(num_scenes):
                if needs_vlm[i]:
                    visual_descriptions.append(vlm_results[i])
                else:
                    source = reuse_from[i]
                    visual_descriptions.append(vlm_results.get(source, "[Reused visual description]"))

            logger.info(f"✅ Completed VLM descriptions: {len(vlm_tasks)} unique + {skipped} reused")

            # Step 3: Simple concatenation (no LLM blending - 2x faster!)
            logger.info(f"🔗 Step 3/3: Blending {num_scenes} content (concatenation)...")
            blended_texts = []
            for i in range(num_scenes):
                transcript = transcript_texts[i]
                visual = visual_descriptions[i]

                # Simple concatenation instead of LLM call
                if transcript and visual:
                    blended = f"{transcript}\n\n{visual}"
                elif transcript:
                    blended = transcript
                elif visual:
                    blended = visual
                else:
                    blended = "[No content available for this scene]"

                blended_texts.append(blended)

            logger.info(f"✅ Completed {num_scenes} content blends (instant!)")

            # Step 4: Assemble final results
            aligned_chunks = []
            for i, scene in enumerate(scenes):
                aligned_chunks.append({
                    'scene_id': scene['scene_id'],
                    'clip_start': scene['start_time'],
                    'clip_end': scene['end_time'],
                    'transcript_text': transcript_texts[i],
                    'visual_description': visual_descriptions[i],
                    'blended_text': blended_texts[i],
                    'key_frame_timestamp': key_frames_data[i]['timestamp']
                })

            return aligned_chunks

        # Run async processing
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            aligned_chunks = loop.run_until_complete(process_all_batched())
            return aligned_chunks
        finally:
            loop.close()

    def _find_overlapping_segments(
        self,
        segments: List[Dict],
        scene_start: float,
        scene_end: float
    ) -> List[Dict]:
        """
        Find transcript segments that overlap with scene time range.
        Uses binary search for O(log n + k) instead of O(n) per scene.

        Overlap logic: !(seg_end < scene_start OR seg_start > scene_end)

        Args:
            segments: List of transcript segments (sorted by start time)
            scene_start: Scene start time in seconds
            scene_end: Scene end time in seconds

        Returns:
            List of overlapping segments
        """
        if not segments:
            return []

        # Binary search: find first segment whose end >= scene_start
        seg_ends = [seg['end'] for seg in segments]
        left = bisect.bisect_left(seg_ends, scene_start)

        overlapping = []
        for i in range(left, len(segments)):
            seg = segments[i]
            if seg['start'] > scene_end:
                break  # All remaining segments start after scene ends
            overlapping.append(seg)

        return overlapping

    @staticmethod
    def _compute_ssim(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
        """Compute structural similarity between two frames (grayscale)."""
        gray_a = cv2.cvtColor(frame_a, cv2.COLOR_BGR2GRAY) if len(frame_a.shape) == 3 else frame_a
        gray_b = cv2.cvtColor(frame_b, cv2.COLOR_BGR2GRAY) if len(frame_b.shape) == 3 else frame_b

        # Resize to same dimensions if needed
        if gray_a.shape != gray_b.shape:
            h = min(gray_a.shape[0], gray_b.shape[0])
            w = min(gray_a.shape[1], gray_b.shape[1])
            gray_a = cv2.resize(gray_a, (w, h))
            gray_b = cv2.resize(gray_b, (w, h))

        # Simple SSIM approximation using mean/std correlation
        mu_a, mu_b = gray_a.mean(), gray_b.mean()
        sigma_a, sigma_b = gray_a.std(), gray_b.std()
        cov = ((gray_a.astype(float) - mu_a) * (gray_b.astype(float) - mu_b)).mean()

        c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
        ssim = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / \
               ((mu_a ** 2 + mu_b ** 2 + c1) * (sigma_a ** 2 + sigma_b ** 2 + c2))
        return float(ssim)

    async def _describe_frame_with_vlm_async(
        self,
        frame: np.ndarray,
        timestamp: float
    ) -> str:
        """
        Describe frame using VLM (extracts text + visual content) - ASYNC VERSION

        Uses same prompt as image_analysis_client.py for consistency.
        Uses ainvoke for true async I/O without thread overhead.

        Args:
            frame: Color frame as BGR numpy array
            timestamp: Frame timestamp in seconds

        Returns:
            Visual description including extracted text

        Raises:
            Exception: If VLM call fails
        """
        try:
            # Encode frame to base64 JPEG
            _, buffer = cv2.imencode('.jpg', frame)
            image_base64 = base64.b64encode(buffer).decode('utf-8')

            # Get VLM (using OpenAI vision)
            llm = get_llm(model="google/gemma-3-27b-it", provider="openrouter")

            # Create prompt (enhanced for maximum visual detail)
            prompt = ChatPromptTemplate.from_messages([
                (
                    "system",
                    "Extract ALL information from this image with EXTREME attention to detail. "
                    "DO NOT include any opening statements, explanations, or closing remarks. "
                    "START AND END with the extracted content only. "
                    "\n\n"
                    "For text-based images:\n"
                    "- Maintain paragraph breaks, bullet points, and formatting\n"
                    "- For tables: preserve row/column structure using markdown table format\n"
                    "- For charts/diagrams: describe visual elements, explain relationships between components, identify trends, and extract all data points and labels\n"
                    "- For formulas/equations: reconstruct them accurately\n"
                    "- Always maintain the original spatial layout and reading order\n"
                    "- Identify headers, footers, page numbers, and other document elements\n"
                    "\n"
                    "For images with NO TEXT or minimal text:\n"
                    "- Provide an EXHAUSTIVELY DETAILED visual description of EVERYTHING visible in the frame\n"
                    "- Describe ALL objects, people, animals, items - no matter how small or insignificant\n"
                    "- Detail the scene setting: indoor/outdoor, location type, environment\n"
                    "- Colors: specific color names, gradients, color relationships\n"
                    "- Lighting: direction, intensity, shadows, highlights, time of day\n"
                    "- Composition: foreground/middle/background elements, depth, perspective\n"
                    "- Spatial relationships: what's next to what, above/below, near/far\n"
                    "- Textures and materials: smooth/rough, reflective/matte, fabric types\n"
                    "- Actions and movement: what people/objects are doing, body language\n"
                    "- Facial expressions and emotions if people are visible\n"
                    "- Text visible anywhere in the scene (signs, labels, screens)\n"
                    "- Brands, logos, identifiable items\n"
                    "- Atmospheric details: weather, mood, ambiance\n"
                    "- Camera angle and framing\n"
                    "- Any unusual or noteworthy details\n"
                    "- Be VERBOSE and COMPREHENSIVE - capture every visible detail\n"
                    "\n"
                    "This is a critical data extraction task - ensure ALL content (text or visual) is captured with MAXIMUM detail and thoroughness."
                ),
                (
                    "user",
                    [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                )
            ])

            # Execute chain with ainvoke for true async
            chain = prompt | llm
            response = await chain.ainvoke({})

            visual_description = response.content

            logger.debug(
                f"VLM described frame at {timestamp:.2f}s: "
                f"{len(visual_description)} chars"
            )

            return visual_description

        except Exception as e:
            logger.error(f"❌ VLM description failed for frame at {timestamp:.2f}s: {str(e)}")
            # Return fallback
            return f"[Visual description unavailable for frame at {timestamp:.2f}s]"

    async def _blend_multimodal_content_async(
        self,
        transcript_text: str,
        visual_description: str
    ) -> str:
        """
        Blend transcript and visual description using LLM - ASYNC VERSION

        Uses ainvoke for true async I/O without thread overhead.

        Args:
            transcript_text: Spoken words from transcript
            visual_description: Visual content from VLM

        Returns:
            Blended multimodal description

        Raises:
            Exception: If blending fails
        """
        try:
            # Handle edge cases
            if not transcript_text and not visual_description:
                return "[No content available for this scene]"

            if not transcript_text:
                return visual_description

            if not visual_description:
                return transcript_text

            # Use LLM to intelligently blend both modalities
            llm = get_llm(model="openai/gpt-5-nano", provider="openrouter")

            prompt = ChatPromptTemplate.from_messages([
                (
                    "system",
                    "You are combining transcript (spoken words) with visual description (what was shown on screen) "
                    "from a video segment. Create a single HIGHLY DETAILED and coherent description that:\n"
                    "- Merges both modalities naturally and comprehensively\n"
                    "- Removes redundancy (don't repeat same info from both sources)\n"
                    "- Keeps ALL important details from BOTH sources - be thorough and verbose\n"
                    "- Preserves ALL specific details: names, numbers, data points, visual elements, actions\n"
                    "- Maintains context and clarity while being exhaustive\n"
                    "- Includes both what was SAID (transcript) and what was SHOWN (visual)\n"
                    "- Be comprehensive - don't summarize or condense, expand and elaborate\n"
                    "- Outputs ONLY the blended content, no preamble or explanation\n\n"
                    "Format the output as detailed, natural paragraphs or structured text. Prioritize completeness over brevity."
                ),
                (
                    "user",
                    "TRANSCRIPT: {transcript}\n\nVISUAL CONTENT: {visual}\n\n"
                    "Blend these into a single coherent description:"
                )
            ])

            chain = prompt | llm
            response = await chain.ainvoke({
                "transcript": transcript_text,
                "visual": visual_description
            })

            blended = response.content

            logger.debug(
                f"Blended content: {len(transcript_text)} + {len(visual_description)} "
                f"→ {len(blended)} chars"
            )

            return blended

        except Exception as e:
            logger.error(f"❌ Blending failed: {str(e)}")
            # Fallback to concatenation
            return f"{transcript_text}\n\n{visual_description}"


# Singleton instance
_video_aligner: Optional[VideoAligner] = None
_client_lock = threading.Lock()


def get_video_aligner() -> VideoAligner:
    """
    Get or create thread-safe VideoAligner singleton instance

    Returns:
        VideoAligner: Singleton client instance
    """
    global _video_aligner

    if _video_aligner is None:
        with _client_lock:
            if _video_aligner is None:
                _video_aligner = VideoAligner()

    return _video_aligner
