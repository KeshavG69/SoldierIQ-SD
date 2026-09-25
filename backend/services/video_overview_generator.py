"""
Video Overview Generator Service
Narrated explainer videos from documents (NotebookLM-style), run as a background task

Pipeline:
    READ        - per-document ranked digests (shared with the infographic's map phase)
    SCRIPT      - structured storyboard: narration + on-screen text + illustration subject per scene
    ILLUSTRATE  - one 16:9 frame per scene from the image model; scene 1 is the style reference for the rest
    NARRATE     - ElevenLabs TTS with character timestamps (falls back to Gemini TTS via OpenRouter)
    COMPOSE     - ffmpeg: Ken Burns motion per scene, exact audio-driven durations, concat to MP4 (+ WebVTT captions)
    STORE       - MP4, poster and chapter thumbnails to iDrive E2; captions + chapters on the workflow row
"""

import asyncio
import base64
import io
import re
import shutil
import tempfile
import uuid
import wave
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image as PILImage

from app.logger import logger
from app.settings import settings
from clients.idrivee2_client import get_idrivee2_client
from clients.postgres_client import get_postgres_client
from clients.ultimate_llm import get_llm
from models.video_overview_models import Storyboard
from services.infographic_generator import (
    STYLE_PROMPTS,
    get_infographic_generator_service,
    _numbers_grounded,
)
from utils.image_gen import generate_image

try:
    from elevenlabs.client import AsyncElevenLabs
except ImportError:  # pragma: no cover
    AsyncElevenLabs = None


SCRIPT_MODEL = "google/gemini-3.8-flash"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
FALLBACK_TTS_MODEL = "google/gemini-3.8-flash-tts"
OPENROUTER_SPEECH_URL = "https://openrouter.ai/api/v1/audio/speech"

FPS = 30
WIDTH, HEIGHT = 1920, 1080
LEAD_IN_S = 0.3      # silence before narration starts in each scene
TAIL_S = 0.6         # hold after narration ends
FADE_S = 0.3
IMAGE_CONCURRENCY = 4
TTS_CONCURRENCY = 2       # ElevenLabs free/starter plans allow very few concurrent requests
TTS_RATE_LIMIT_RETRIES = 5
ENCODE_CONCURRENCY = 2
STALE_AFTER = timedelta(minutes=30)

FORMATS = {
    "explainer": {"scenes": "8-10", "words": "45-70", "label": "explainer"},
    "brief": {"scenes": "4-5", "words": "30-45", "label": "short briefing"},
}

VOICES = {
    "sarah": {"elevenlabs": "EXAVITQu4vr4xnSDxMaL", "gemini": "Kore"},
    "brian": {"elevenlabs": "nPczCjzI2devNBz1zQrb", "gemini": "Charon"},
    "george": {"elevenlabs": "JBFqnCBsd6RMkjVDRZzb", "gemini": "Iapetus"},
}

VIDEO_STYLES = {
    "classic": (
        "A clean, modern editorial explainer frame on a warm off-white background (#F7F6F2). Deep ink (#16202A) text, "
        "deep teal (#0E6E6E) primary shapes and a single warm amber accent (#F2A541). Flat vector illustration with a subtle paper grain, "
        "a crisp geometric sans-serif in the spirit of Inter for all text, generous whitespace."
    ),
    "whiteboard": (
        "A hand-drawn whiteboard explainer frame: clean white board background, black and blue dry-erase marker line drawings, "
        "a single red marker accent, neat hand-lettered marker headings, simple confident sketch illustrations with slight marker texture."
    ),
    "watercolor": (
        "A soft watercolor illustration on textured cold-press paper: muted blue, sage and ochre washes with fine ink outlines, "
        "elegant dark-ink serif headings, calm and airy composition."
    ),
    "papercraft": (
        "A layered cut-paper papercraft look: stacked paper shapes with soft drop shadows between layers, a warm muted palette "
        "(terracotta, sand, teal, cream), bold rounded sans-serif headings set on a paper banner."
    ),
    "retro_print": (
        "A retro risograph print aesthetic on cream stock (#F4EFE3): three spot colors (fluorescent pink #FF48B0, teal #00838A, "
        "mustard #E3A92B) with halftone textures and slight misregistration, bold condensed display type."
    ),
    "tactical": STYLE_PROMPTS["tactical"],
}

TEXT_RULES = """TEXT RULES (critical):
- Render every quoted string exactly as written, with exact spelling, numbers and capitalization. Never shorten or truncate a string. Do not render the quote marks.
- Everything outside quotes (style, colors, hex codes, fonts, layout and illustration descriptions) is an instruction, not text: never draw it.
- Do not add ANY other text: no captions, labels, logos, watermarks, URLs, dates, page numbers or subtitles.
- The illustration itself contains no text, letters or numbers.
- All text is large, sharp and legible, and sits well inside the margins."""


def _probe_duration(path: Path) -> float:
    import subprocess

    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return float(out)


def _vtt_time(t: float) -> str:
    t = max(t, 0.0)
    return f"{int(t // 3600):02}:{int(t % 3600 // 60):02}:{t % 60:06.3f}"


def _word_timings(alignment) -> List[Tuple[str, float, float]]:
    """Group ElevenLabs character alignment into (word, start, end)"""
    words, word, start, end = [], "", None, 0.0
    for ch, st, en in zip(alignment.characters, alignment.character_start_times_seconds, alignment.character_end_times_seconds):
        if ch.isspace():
            if word:
                words.append((word, start, end))
                word = ""
        else:
            if not word:
                start = st
            word += ch
            end = en
    if word:
        words.append((word, start, end))
    return words


def _estimated_word_timings(text: str, duration: float) -> List[Tuple[str, float, float]]:
    """Without TTS timestamps, spread words across the clip in proportion to their length"""
    words = text.split()
    total = sum(len(w) + 1 for w in words) or 1
    timings, t = [], 0.0
    for w in words:
        span = duration * (len(w) + 1) / total
        timings.append((w, t, t + span))
        t += span
    return timings


def _cues(words: List[Tuple[str, float, float]], offset: float, max_words: int = 8, max_span: float = 3.2) -> List[Tuple[float, float, str]]:
    cues, chunk = [], []
    for w in words:
        if chunk and (len(chunk) >= max_words or w[2] - chunk[0][1] > max_span):
            cues.append((chunk[0][1] + offset, chunk[-1][2] + offset, " ".join(x[0] for x in chunk)))
            chunk = []
        chunk.append(w)
        if w[0].endswith((".", "?", "!")) and len(chunk) >= 3:
            cues.append((chunk[0][1] + offset, chunk[-1][2] + offset, " ".join(x[0] for x in chunk)))
            chunk = []
    if chunk:
        cues.append((chunk[0][1] + offset, chunk[-1][2] + offset, " ".join(x[0] for x in chunk)))

    # Fold a dangling 1-2 word tail (e.g. "immediately.") into the cue before it
    merged: List[Tuple[float, float, str]] = []
    for start, end, text in cues:
        if merged and len(text.split()) <= 2 and not merged[-1][2].endswith((".", "?", "!")):
            prev = merged.pop()
            merged.append((prev[0], end, f"{prev[2]} {text}"))
        else:
            merged.append((start, end, text))
    return merged


class VideoOverviewGeneratorService:
    """Service for generating narrated video overviews"""

    def __init__(self):
        self.postgres_client = get_postgres_client()
        self.idrive = get_idrivee2_client()
        self.storyboard_llm = get_llm(model=SCRIPT_MODEL, provider="openrouter").with_structured_output(Storyboard)
        self.elevenlabs = (
            AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
            if settings.ELEVENLABS_API_KEY and AsyncElevenLabs else None
        )

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    async def create_pending(self, document_ids: List[str], options: Dict[str, Any], user_id: str, organization_id: str) -> str:
        """Insert a 'processing' workflow row; the caller schedules run_generation()"""
        workflow_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        await self.postgres_client.insert_workflow({
            "id": workflow_id,
            "type": "video_overview",
            "document_ids": document_ids,
            "user_id": user_id,
            "organization_id": organization_id,
            "status": "processing",
            "data": {"title": None, "settings": options, "stage": "queued"},
            "created_at": now,
            "updated_at": now,
        })
        logger.info(f"🎬 Video overview {workflow_id} queued for {len(document_ids)} documents")
        return workflow_id

    async def _set_stage(self, workflow_id: str, options: Dict[str, Any], stage: str) -> None:
        try:
            await self.postgres_client.update_workflow(workflow_id, {
                "data": {"title": None, "settings": options, "stage": stage},
                "updated_at": datetime.now(timezone.utc),
            })
        except Exception as e:
            logger.warning(f"⚠️ Could not update stage for video {workflow_id}: {e}")

    async def run_generation(self, workflow_id: str, document_ids: List[str], options: Dict[str, Any], organization_id: str) -> None:
        """Background task: run the full pipeline and record the result on the workflow row"""
        work = Path(tempfile.mkdtemp(prefix=f"video_{workflow_id[:8]}_")).resolve()
        try:
            await self._set_stage(workflow_id, options, "reading")
            digests = await get_infographic_generator_service()._map_digest_documents(document_ids, options.get("focus"))
            if not digests:
                raise Exception("No content could be extracted from the selected documents")

            await self._set_stage(workflow_id, options, "scripting")
            storyboard = await self._write_storyboard(digests, options)

            await self._set_stage(workflow_id, options, "illustrating")
            images, image_cost = await self._illustrate(storyboard, options, work)

            await self._set_stage(workflow_id, options, "narrating")
            narration = await self._narrate(storyboard, options, work)

            await self._set_stage(workflow_id, options, "composing")
            video_path, duration, chapters, captions_vtt = await self._compose(storyboard, images, narration, work)

            # STORE
            prefix = f"video-overviews/{organization_id}/{workflow_id}"
            video_key, poster_key = f"{prefix}/video.mp4", f"{prefix}/poster.jpg"
            await self.idrive.upload_file(io.BytesIO(video_path.read_bytes()), video_key, "video/mp4")
            await self.idrive.upload_file(io.BytesIO(self._jpeg(images[0], 1280)), poster_key, "image/jpeg")
            for i, chapter in enumerate(chapters):
                key = f"{prefix}/chapters/scene-{i + 1:02d}.jpg"
                await self.idrive.upload_file(io.BytesIO(self._jpeg(images[i], 480)), key, "image/jpeg")
                chapter["thumb_key"] = key

            engines = sorted({n["engine"] for n in narration})
            await self.postgres_client.update_workflow(workflow_id, {
                "status": "completed",
                "data": {
                    "title": storyboard["title"],
                    "settings": options,
                    "stage": "completed",
                    "duration_s": round(duration, 1),
                    "scene_count": len(storyboard["scenes"]),
                    "video_key": video_key,
                    "poster_key": poster_key,
                    "chapters": chapters,
                    "captions_vtt": captions_vtt,
                    "transcript": [s["narration"] for s in storyboard["scenes"]],
                    "sources": sorted({d["filename"] for d in digests}),
                    "tts_engines": engines,
                    "tts_characters": sum(len(s["narration"]) for s in storyboard["scenes"]),
                    "image_cost_usd": round(image_cost, 4),
                },
                "updated_at": datetime.now(timezone.utc),
            })
            logger.info(f"✅ Video overview {workflow_id} completed: '{storyboard['title']}', {duration:.0f}s, TTS={engines}")

        except Exception as e:
            logger.error(f"❌ Video overview {workflow_id} failed: {e}")
            try:
                await self.postgres_client.update_workflow(workflow_id, {
                    "status": "failed",
                    "data": {"title": None, "settings": options, "stage": "failed", "error": str(e)},
                    "updated_at": datetime.now(timezone.utc),
                })
            except Exception as update_error:
                logger.error(f"❌ Failed to mark video {workflow_id} as failed: {update_error}")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ------------------------------------------------------------------
    # SCRIPT
    # ------------------------------------------------------------------

    async def _write_storyboard(self, digests: List[Dict[str, Any]], options: Dict[str, Any]) -> Dict[str, Any]:
        fmt = FORMATS.get(options.get("format", "explainer"), FORMATS["explainer"])
        blocks = []
        for d in digests:
            digest = d["digest"]
            lines = [f"Document: {d['filename']}", f"Main point: {digest.main_point}"]
            for ins in digest.insights:
                value = f" [value: {ins.value}]" if ins.value else ""
                lines.append(f"- ({ins.kind}, importance {ins.importance}){value} {ins.claim}")
            blocks.append("\n".join(lines))
        focus = options.get("focus")
        focus_rule = f"\n- The viewer asked to focus on: {focus}. Prioritise it." if focus else ""

        prompt = f"""You are writing a narrated {fmt['label']} video that explains these documents to busy professional viewers.

Write a storyboard of {fmt['scenes']} scenes. Scene 1 introduces the topic and why it matters; the last scene wraps up with the key takeaway. The middle scenes each cover one idea, in an order that tells a clear story.

NARRATION (spoken by one narrator):
- {fmt['words']} words per scene, conversational and clear, written for the ear: short sentences, no bullet lists, no parentheses or abbreviations the narrator can't read naturally.
- Flow from scene to scene; don't repeat the headline verbatim.

ON-SCREEN TEXT (drawn into the scene image, so keep it minimal):
- headline: 3-8 words. points: 0-3 items of 2-6 words. Use stat_value + stat_label for scenes built around one key number.
- Copy numbers and dates exactly as given; never invent, round or compute numbers.

VISUAL: describe a concrete illustration subject for each scene (objects, setting, metaphor) - no text in it.
Set "source" to the filename each scene mainly draws from. Use only the material below; no outside facts.{focus_rule}

Material:
{chr(10).join(blocks)}"""

        storyboard: Storyboard = await self.storyboard_llm.ainvoke(prompt)
        data = storyboard.model_dump()
        if not data["scenes"]:
            raise Exception("Storyboard has no scenes")

        # On-screen numbers must come from the sources (narration is spoken context, checked less strictly)
        padded_sources = [f" {d['normalized_content']} " for d in digests]
        for scene in data["scenes"]:
            scene["points"] = [p for p in scene["points"][:3] if _numbers_grounded(p, padded_sources)]
            stat_text = " ".join(filter(None, [scene.get("stat_value"), scene.get("stat_label")]))
            if stat_text and not _numbers_grounded(stat_text, padded_sources):
                logger.warning(f"⚠️ Dropping ungrounded stat: {stat_text}")
                scene["stat_value"] = scene["stat_label"] = None
        logger.info(f"📝 Storyboard '{data['title']}': {len(data['scenes'])} scenes, {sum(len(s['narration']) for s in data['scenes'])} narration chars")
        return data

    # ------------------------------------------------------------------
    # ILLUSTRATE
    # ------------------------------------------------------------------

    def _scene_prompt(self, storyboard: Dict[str, Any], index: int, options: Dict[str, Any]) -> str:
        scene = storyboard["scenes"][index]
        total = len(storyboard["scenes"])
        style = VIDEO_STYLES.get(options.get("style", "classic"), VIDEO_STYLES["classic"])

        content = []
        if index == 0:
            content.append(f'- Title: "{storyboard["title"]}"')
            content.append(f'- Subtitle: "{storyboard["subtitle"]}"')
            layout = "title card: the title large on the left third, the subtitle beneath it, and the illustration filling the right side"
        else:
            content.append(f'- Headline: "{scene["headline"]}"')
            if scene.get("stat_value"):
                label = f' with the small label "{scene["stat_label"]}"' if scene.get("stat_label") else ""
                content.append(f'- One big number: "{scene["stat_value"]}"{label}')
                layout = "the headline at top left, the big number very large as the focal point on one side, the illustration on the other"
            else:
                layout = "the headline at top left, the illustration as the large focal point, any short points stacked neatly beside it"
            for p in scene.get("points") or []:
                content.append(f'- Short point: "{p}"')

        return f"""Generate a single 16:9 frame for a narrated explainer video (scene {index + 1} of {total}).
This brief is instructions for the illustrator. The ONLY text that may appear in the image is the quoted strings in CONTENT.

ART DIRECTION: {style}

COMPOSITION: 16:9 landscape, {layout}. Keep generous 8% margins on every side: the frame slowly zooms and pans, so nothing important may sit near an edge. One clear focal point, calm background, uncluttered.

ILLUSTRATION: {scene["visual"]}

CONTENT:
{chr(10).join(content)}

{TEXT_RULES}"""

    async def _illustrate(self, storyboard: Dict[str, Any], options: Dict[str, Any], work: Path) -> Tuple[List[bytes], float]:
        scenes = storyboard["scenes"]
        # Scene 1 first: it becomes the style reference that keeps every other frame consistent
        first, cost = await generate_image(self._scene_prompt(storyboard, 0, options), "16:9")
        images: List[Optional[bytes]] = [first] + [None] * (len(scenes) - 1)
        total_cost = cost or 0.0
        semaphore = asyncio.Semaphore(IMAGE_CONCURRENCY)

        async def render(i: int):
            nonlocal total_cost
            async with semaphore:
                prompt = self._scene_prompt(storyboard, i, options) + (
                    "\n\nSTYLE REFERENCE: match the attached frame exactly in palette, typography, illustration style, "
                    "background and margins, so this looks like the next scene of the same video. Do not copy its text or subject."
                )
                img, c = await generate_image(prompt, "16:9", reference_images=[first])
                images[i] = img
                total_cost += c or 0.0

        await asyncio.gather(*[render(i) for i in range(1, len(scenes))])
        for i, img in enumerate(images):
            (work / f"scene-{i + 1:02d}.png").write_bytes(img)
        logger.info(f"🖼️ Illustrated {len(images)} scenes (${total_cost:.3f})")
        return images, total_cost

    @staticmethod
    def _jpeg(png: bytes, width: int) -> bytes:
        with PILImage.open(io.BytesIO(png)) as im:
            im = im.convert("RGB")
            im.thumbnail((width, width))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=82)
            return buf.getvalue()

    # ------------------------------------------------------------------
    # NARRATE
    # ------------------------------------------------------------------

    async def _narrate(self, storyboard: Dict[str, Any], options: Dict[str, Any], work: Path) -> List[Dict[str, Any]]:
        voice = VOICES.get(options.get("voice", "sarah"), VOICES["sarah"])
        scenes = storyboard["scenes"]
        results: List[Optional[Dict[str, Any]]] = [None] * len(scenes)
        state = {"use_elevenlabs": self.elevenlabs is not None}
        semaphore = asyncio.Semaphore(TTS_CONCURRENCY)

        async def speak(i: int):
            async with semaphore:
                text = scenes[i]["narration"]
                if state["use_elevenlabs"]:
                    for attempt in range(TTS_RATE_LIMIT_RETRIES + 1):
                        try:
                            r = await self.elevenlabs.text_to_speech.convert_with_timestamps(
                                voice_id=voice["elevenlabs"],
                                text=text,
                                model_id=ELEVENLABS_MODEL,
                                output_format="mp3_44100_128",
                                previous_text=scenes[i - 1]["narration"] if i > 0 else None,
                                next_text=scenes[i + 1]["narration"] if i + 1 < len(scenes) else None,
                            )
                            path = work / f"narration-{i + 1:02d}.mp3"
                            path.write_bytes(base64.b64decode(r.audio_base_64))
                            results[i] = {"path": path, "words": _word_timings(r.alignment), "engine": "elevenlabs"}
                            return
                        except Exception as e:
                            body = str(getattr(e, "body", e))
                            # Concurrency limit is transient: wait and retry. Anything else (credits used up,
                            # paid-only voice, outage) switches the rest of this video to the fallback voice.
                            if getattr(e, "status_code", None) == 429 and "concurrent" in body and attempt < TTS_RATE_LIMIT_RETRIES:
                                await asyncio.sleep(1.5 * (attempt + 1))
                                continue
                            state["use_elevenlabs"] = False
                            logger.warning(f"⚠️ ElevenLabs failed ({getattr(e, 'status_code', '')} {body[:160]}); using {FALLBACK_TTS_MODEL}")
                            break
                pcm = await self._gemini_tts(text, voice["gemini"])
                path = work / f"narration-{i + 1:02d}.wav"
                with wave.open(str(path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(24000)
                    w.writeframes(pcm)
                results[i] = {"path": path, "words": None, "engine": "gemini"}

        await asyncio.gather(*[speak(i) for i in range(len(scenes))])

        # If ElevenLabs failed midway, keep one consistent voice: re-voice everything with the fallback
        engines = {r["engine"] for r in results}
        if len(engines) > 1:
            logger.info("🔁 Mixed TTS engines; re-voicing all scenes with the fallback for a consistent voice")
            state["use_elevenlabs"] = False
            await asyncio.gather(*[speak(i) for i in range(len(scenes)) if results[i]["engine"] == "elevenlabs"])

        for r, scene in zip(results, scenes):
            r["duration"] = _probe_duration(r["path"])
            if r["words"] is None:
                r["words"] = _estimated_word_timings(scene["narration"], r["duration"])
        logger.info(f"🎙️ Narrated {len(results)} scenes with {sorted({r['engine'] for r in results})}, {sum(r['duration'] for r in results):.0f}s total")
        return results

    async def _gemini_tts(self, text: str, voice: str) -> bytes:
        last_error: Optional[Exception] = None
        for _ in range(2):
            try:
                async with httpx.AsyncClient(timeout=180) as client:
                    response = await client.post(
                        OPENROUTER_SPEECH_URL,
                        headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                        json={"model": FALLBACK_TTS_MODEL, "input": text, "voice": voice, "response_format": "pcm"},
                    )
                response.raise_for_status()
                return response.content  # 24 kHz, 16-bit, mono PCM
            except Exception as e:
                last_error = e
        raise Exception(f"Narration failed: {last_error}")

    # ------------------------------------------------------------------
    # COMPOSE
    # ------------------------------------------------------------------

    @staticmethod
    def _motion(index: int, frames: int) -> str:
        """Alternate gentle Ken Burns moves so consecutive scenes don't feel identical"""
        n = max(frames - 1, 1)
        center = "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
        # Kept subtle (<=3%): the image model sometimes places text close to the frame edge
        moves = [
            f"z='1+0.03*on/{n}':{center}",                                   # slow push in
            f"z='1.03-0.03*on/{n}':{center}",                                # slow pull out
            f"z='1.03':x='(iw-iw/zoom)*on/{n}':y='ih/2-ih/zoom/2'",          # pan left -> right
            f"z='1.03':x='(iw-iw/zoom)*(1-on/{n})':y='ih/2-ih/zoom/2'",      # pan right -> left
        ]
        return moves[index % len(moves)]

    async def _run_ffmpeg(self, args: List[str]) -> None:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0:
            raise Exception(f"ffmpeg failed: {err.decode('utf-8', 'replace')[-500:]}")

    async def _compose(
        self,
        storyboard: Dict[str, Any],
        images: List[bytes],
        narration: List[Dict[str, Any]],
        work: Path,
    ) -> Tuple[Path, float, List[Dict[str, Any]], str]:
        semaphore = asyncio.Semaphore(ENCODE_CONCURRENCY)
        durations = [LEAD_IN_S + n["duration"] + TAIL_S for n in narration]

        async def encode(i: int):
            async with semaphore:
                dur = durations[i]
                frames = round(dur * FPS)
                delay_ms = int(LEAD_IN_S * 1000)
                vf = (
                    f"[0:v]scale=2880:1620:force_original_aspect_ratio=increase,crop=2880:1620,"
                    f"zoompan={self._motion(i, frames)}:d=1:s={WIDTH}x{HEIGHT}:fps={FPS},"
                    f"fade=t=in:st=0:d={FADE_S},fade=t=out:st={dur - FADE_S:.3f}:d={FADE_S},format=yuv420p[v];"
                    f"[1:a]adelay={delay_ms}|{delay_ms},apad,atrim=0:{dur:.3f},"
                    f"aformat=sample_rates=48000:channel_layouts=stereo[a]"
                )
                await self._run_ffmpeg([
                    "-loop", "1", "-framerate", str(FPS), "-i", str(work / f"scene-{i + 1:02d}.png"),
                    "-i", str(narration[i]["path"]),
                    "-filter_complex", vf, "-map", "[v]", "-map", "[a]",
                    "-frames:v", str(frames), "-t", f"{dur:.3f}",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", str(FPS),
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                    str(work / f"segment-{i + 1:02d}.mp4"),
                ])

        await asyncio.gather(*[encode(i) for i in range(len(narration))])

        concat_list = work / "segments.txt"
        concat_list.write_text("".join(f"file 'segment-{i + 1:02d}.mp4'\n" for i in range(len(narration))))
        video_path = work / "video.mp4"
        await self._run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", "-movflags", "+faststart", str(video_path)])

        # Chapters and captions from the actual per-scene durations
        chapters, cues, start = [], [], 0.0
        for i, (scene, n) in enumerate(zip(storyboard["scenes"], narration)):
            chapters.append({"title": scene["chapter"], "start": round(start, 2)})
            cues.extend(_cues(n["words"], start + LEAD_IN_S))
            start += durations[i]
        vtt = "WEBVTT\n\n" + "".join(
            f"{i + 1}\n{_vtt_time(a)} --> {_vtt_time(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(cues)
        )
        duration = _probe_duration(video_path)
        logger.info(f"🎞️ Composed {duration:.0f}s video from {len(narration)} scenes")
        return video_path, duration, chapters, vtt

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _effective_status(self, status: str, updated_at: Optional[datetime]) -> str:
        if status == "processing" and updated_at and datetime.now(timezone.utc) - updated_at > STALE_AFTER:
            return "failed"
        return status

    async def list_videos(self, user_id: str, organization_id: str) -> List[Dict[str, Any]]:
        """List the user's video overviews (summaries + poster, newest first)"""
        workflows = await self.postgres_client.find_workflow_summaries_by_user(
            "video_overview", user_id, organization_id, exclude_data_keys=["captions_vtt", "transcript", "chapters"]
        )
        results = []
        for w in workflows:
            data = w["data"]
            results.append({
                "workflow_id": w["id"],
                "status": self._effective_status(w.get("status"), w.get("updated_at")),
                "stage": data.get("stage"),
                "title": data.get("title"),
                "settings": data.get("settings", {}),
                "duration_s": data.get("duration_s"),
                "document_count": w.get("document_count") or 0,
                "poster_url": await self.idrive.generate_presigned_url(data["poster_key"]) if data.get("poster_key") else None,
                "created_at": w["created_at"].isoformat() if w.get("created_at") else None,
            })
        return results

    async def get_video(self, workflow_id: str, user_id: str, organization_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Fetch a video overview, only if it belongs to the requesting user and organization"""
        workflow = await self.postgres_client.find_workflow_by_id(workflow_id, "video_overview")
        if not workflow or workflow.get("user_id") != user_id or workflow.get("organization_id") != organization_id:
            return None

        data = workflow["data"]
        status = self._effective_status(workflow.get("status"), workflow.get("updated_at"))
        title = data.get("title")
        filename = re.sub(r"[^\w\- ]", "", title or "video-overview").strip().replace(" ", "_") or "video-overview"
        video_key = data.get("video_key")

        chapters = []
        for c in data.get("chapters") or []:
            chapters.append({
                "title": c["title"],
                "start": c["start"],
                "thumb_url": await self.idrive.generate_presigned_url(c["thumb_key"], expiration=4 * 3600) if c.get("thumb_key") else None,
            })

        return {
            "workflow_id": workflow["id"],
            "status": status,
            "stage": data.get("stage"),
            "title": title,
            "settings": data.get("settings", {}),
            "duration_s": data.get("duration_s"),
            "chapters": chapters,
            "captions_vtt": data.get("captions_vtt"),
            "transcript": data.get("transcript", []),
            "sources": data.get("sources", []),
            "tts_engines": data.get("tts_engines", []),
            "document_ids": workflow.get("document_ids", []),
            "document_count": len(workflow.get("document_ids") or []),
            "error": data.get("error") or ("Generation timed out" if status == "failed" and workflow.get("status") == "processing" else None),
            # 4h links: long enough to finish watching a video opened near the end of a session
            "video_url": await self.idrive.generate_presigned_url(video_key, expiration=4 * 3600) if video_key else None,
            "download_url": await self.idrive.generate_presigned_url(video_key, expiration=4 * 3600, download_filename=f"{filename}.mp4") if video_key else None,
            "poster_url": await self.idrive.generate_presigned_url(data["poster_key"], expiration=4 * 3600) if data.get("poster_key") else None,
            "created_at": workflow["created_at"].isoformat() if workflow.get("created_at") else None,
        }


# Singleton instance
_video_overview_generator_service = None


def get_video_overview_generator_service() -> VideoOverviewGeneratorService:
    """Get or create video overview generator service singleton"""
    global _video_overview_generator_service
    if _video_overview_generator_service is None:
        _video_overview_generator_service = VideoOverviewGeneratorService()
    return _video_overview_generator_service
