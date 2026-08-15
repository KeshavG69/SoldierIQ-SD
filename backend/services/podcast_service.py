"""
Podcast Service (Scripting Phase)
Generates multi-speaker podcast scripts from documents using MapReduce (Gemini via OpenRouter).
"""

import asyncio
import uuid
from typing import List, Dict, Any, Optional
from langchain_core.prompts import ChatPromptTemplate

from clients.postgres_client import get_postgres_client
from models.podcast import PodcastScript, PodcastSegment
from clients.ultimate_llm import get_llm
from app.logger import logger
from app.settings import settings
from clients.idrivee2_client import get_idrivee2_client
import io
from pydub import AudioSegment

# Try importing ElevenLabs, handle if missing but dependency should be there
try:
    from elevenlabs.client import AsyncElevenLabs
    from elevenlabs import VoiceSettings
except ImportError:
    logger.warning("ElevenLabs SDK not found")
    AsyncElevenLabs = None


class PodcastService:
    """Service for generating podcast scripts from documents"""

    # Voice IDs (Defaults)
    VOICE_SPEAKER_1 = "21m00Tcm4TlvDq8ikWAM"  # Rachel (Female)
    VOICE_SPEAKER_2 = "AZnzlk1XvdvUeBnXmlld"  # Dombi (Male)

    def __init__(self):
        """Initialize podcast service"""

        self.llm_flash = get_llm(model="google/gemini-3-flash-preview", provider="openrouter")

        # Structured output for final script (ensure valid JSON)
        self.structured_llm = self.llm_flash.with_structured_output(PodcastScript)

        self.postgres_client = get_postgres_client()
        self.idrive = get_idrivee2_client()

        if settings.ELEVENLABS_API_KEY and AsyncElevenLabs:
            self.elevenlabs = AsyncElevenLabs(api_key=settings.ELEVENLABS_API_KEY)
        else:
            self.elevenlabs = None
            logger.warning("ElevenLabs client not initialized (Missing Key or SDK)")

    async def generate_script(self, document_ids: List[str]) -> PodcastScript:
        """
        Generate a podcast script from a list of document IDs.
        
        Args:
            document_ids: List of MongoDB document ID strings
            
        Returns:
            PodcastScript object
        """
        if not document_ids:
            raise ValueError("No document IDs provided for script generation")
            
        logger.info(f"🎙️ Fetching {len(document_ids)} documents for podcast generation...")

        # Fetch documents from PostgreSQL
        documents = []
        for doc_id in document_ids:
            doc = await self.postgres_client.find_document_by_id(doc_id)
            if doc:
                documents.append(doc)
            else:
                logger.warning(f"Document not found: {doc_id}")
        
        if not documents:
            raise ValueError("No valid documents found from provided IDs")

        logger.info(f"✅ Fetched {len(documents)} documents. Starting generation...")
        return await self._map_reduce_pipeline(documents)

    async def _map_reduce_pipeline(self, documents: List[Dict]) -> PodcastScript:
        """
        MapReduce Strategy:
        1. Map: Summarize each document individually (Parallel with Semaphore)
        2. Reduce: Synthesize script from summaries
        """
        logger.info(f"🗺️ Starting MapReduce Pipeline for {len(documents)} documents...")
        
        # --- Step A: MAP (Summarize each document) ---
        semaphore = asyncio.Semaphore(5)
        
        summary_prompt = ChatPromptTemplate.from_template(
            """Analyze this document and extract the most interesting, surprising, and key information. 
            Focus on details that would make for good podcast conversation (anecdotes, facts, arguments).
            
            DOCUMENT: {filename}
            CONTENT:
            {text}
            """
        )

        async def process_doc(doc):
            async with semaphore:
                content = doc.get("raw_content", "")
                if not content:
                    return ""

                filename = doc.get("file_name", "Unknown Doc")
                try:
                    # We use the standard LLM (string output) for summaries, not structured
                    result = await self.llm_flash.ainvoke(
                        summary_prompt.format_messages(text=content, filename=filename)
                    )
                    return result.content
                except Exception as e:
                    logger.error(f"Error summarizing document {filename}: {e}")
                    return ""

        logger.info(f"⏳ Summarizing {len(documents)} documents in parallel (Concurrency: 5)...")
        tasks = [process_doc(doc) for doc in documents]
        summaries = await asyncio.gather(*tasks)
        
        # Filter empty summaries
        valid_summaries = [s for s in summaries if s]
        
        if not valid_summaries:
            raise ValueError("Failed to generate any summaries from documents")
            
        combined_summary = "\n\n".join(valid_summaries)
        logger.info(f"✅ Map Phase Complete: {len(valid_summaries)} summaries generated")

        # --- Step B: REDUCE (Generate Script) ---

        logger.info("📝 Synthesizing Final Script...")
        
        # Add current datetime for context
        from datetime import datetime
        current_context = f"Current Date/Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        current_context += "Location: Unknown (Default)\n"
        
        script_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a producer for a wildly popular tech/science podcast.
            Create a script for a 2-host podcast episode based on the provided research summaries.
            
            Host 1 (Speaker 1): Enthusiastic, curious, asks questions.
            Host 2 (Speaker 2): Expert, analytical, explains concepts.
            
            Structure:
            1. Title & Brief Summary.
            2. Dialogue: 10-15 exchanges.
            
            Style: Conversational, "Deep Dive" style, includes banter, "ums", and natural flow.
            Make sure to add natural pauses and interruptions to make it more realistic.
            Ensure the content is accurate to the source material provided.
            
            CONTEXT:
            {context}
            """),
            ("user", "Research Material:\n{summaries}")
        ])

        # Use structured output to define the PodcastScript object
        script: PodcastScript = await self.structured_llm.ainvoke(
            script_prompt.format_messages(
                summaries=combined_summary,
                context=current_context
            )
        )
        
        logger.info(f"✅ Script Generation Complete: '{script.title}' with {len(script.segments)} segments")
        return script


    async def generate_podcast(self, document_ids: List[str], organization_id: str, podcast_id: str = None) -> Dict[str, Any]:
        """
        Full Pipeline: Script -> Audio -> Upload
        Supports optional podcast_id for async status updates.
        """
        try:
            # 1. Generate Script
            script = await self.generate_script(document_ids)

            # Update status if podcast_id provided
            if podcast_id:
                await self.postgres_client.update_podcast(
                    podcast_id=podcast_id,
                    updates={
                        "status": "script_generated",
                        "title": script.title,
                        "summary": script.summary,
                        "script": script.model_dump()
                    }
                )

            # 2. Generate Audio
            audio_url = None
            if not self.elevenlabs:
                logger.warning("ElevenLabs not configured, skipping audio generation")
                if podcast_id:
                    await self.postgres_client.update_podcast(
                        podcast_id=podcast_id,
                        updates={"status": "completed", "error_message": "Audio skipped (No API Key)"}
                    )
            else:
                audio_file_key = await self._generate_audio(script.segments, organization_id, podcast_id)
                # _generate_audio now handles the final update if podcast_id is passed?
                # Actually let's keep _generate_audio focused on audio and do the final update here.

                if podcast_id:
                    await self.postgres_client.update_podcast(
                        podcast_id=podcast_id,
                        updates={"status": "completed", "audio_file_key": audio_file_key}
                    )

            return {
                "title": script.title,
                "summary": script.summary,
                "script": script.model_dump(),
                "audio_file_key": audio_file_key
            }
            
        except Exception as e:
            logger.error(f"Podcast generation failed: {e}")
            if podcast_id:
                await self.postgres_client.update_podcast(
                    podcast_id=podcast_id,
                    updates={"status": "failed", "error_message": str(e)}
                )
            raise e

    async def _generate_audio(self, segments: List[PodcastSegment], organization_id: str, podcast_id: str = None) -> str:
        """
        Generate audio for each segment, stitch, and upload.
        """
        logger.info(f"🎙️ Generating Audio (ElevenLabs) for {len(segments)} segments...")
        
        combined_audio = AudioSegment.empty()
        
        for i, seg in enumerate(segments):
            # Alternate voices 
            # Check speaker label to determine voice
            voice_id = self.VOICE_SPEAKER_1 if "1" in seg.speaker else self.VOICE_SPEAKER_2
            
            try:
                # Generate audio stream (Non-streaming)
                audio_bytes = b""
                async for chunk in self.elevenlabs.text_to_speech.convert(
                    text=seg.text,
                    voice_id=voice_id,
                    model_id="eleven_multilingual_v2",
                    output_format="mp3_44100_128"
                ):
                    audio_bytes += chunk
                
                if not audio_bytes:
                    logger.warning(f"No audio generated for segment {i}")
                    continue
                
                logger.info(f"Segment {i}: Generated {len(audio_bytes)} bytes")

                # Load into PyDub
                segment_audio = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
                logger.info(f"Segment {i}: Duration {len(segment_audio)}ms")
                combined_audio += segment_audio
                
                # Add a small natural pause between speakers (0.5s)
                combined_audio += AudioSegment.silent(duration=500) 
                
            except Exception as e:
                logger.error(f"Error generating audio for segment {i}: {e}")
                # Continue preventing total failure if one segment fails?
                # Ideally we want a fail-safe or retry. For now, log and continue.
                continue

        # Export full episode
        logger.info("💾 Stitching and uploading full episode...")
        buffer = io.BytesIO()
        combined_audio.export(buffer, format="mp3")
        buffer.seek(0)
        
        # Upload to iDrive E2
        # Use provided ID or generate
        if not podcast_id:
            podcast_id = str(uuid.uuid4())

        file_key = f"podcasts/{organization_id}/{podcast_id}/full_episode.mp3"
        await self.idrive.upload_file(buffer, file_key, "audio/mpeg")
        
        # Determine public URL (presigned or public bucket URL if public)
        # For now, return the file_key so it can be used to generate presigned URLs on demand
        return file_key

# Singleton
_podcast_service = None

def get_podcast_service() -> PodcastService:
    global _podcast_service
    if _podcast_service is None:
        _podcast_service = PodcastService()
    return _podcast_service
