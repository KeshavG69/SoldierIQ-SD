"""
Report Generator Service
Generates comprehensive reports using Map-Reduce pattern
"""

import asyncio
import uuid
from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime

from clients.postgres_client import get_postgres_client
from clients.ultimate_llm import get_llm
from app.logger import logger


class ReportGeneratorService:
    """Service for generating reports using Map-Reduce"""

    def __init__(self):
        """Initialize report generator service"""
        self.postgres_client = get_postgres_client()
        self.llm = get_llm(model="google/gemini-3-flash-preview", provider="openrouter")

    async def generate_report_stream(
        self,
        document_ids: List[str],
        prompt: str,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """
        Generate report using Map-Reduce with streaming progress updates

        MAP Phase: Summarize each document
        REDUCE Phase: Combine summaries with user prompt into final report

        Args:
            document_ids: List of document IDs to process
            prompt: User's report generation prompt (from selected format)
            user_id: Optional user ID
            organization_id: Optional organization ID

        Yields:
            Server-Sent Events with progress and final report
        """
        try:
            total_docs = len(document_ids)
            logger.info(f"📊 Starting report generation for {total_docs} documents")

            # Send start event
            yield f"event: start\ndata: {{\"message\": \"Starting report generation\"}}\n\n"

            # MAP Phase: Summarize each document in parallel
            yield f"event: progress\ndata: {{\"message\": \"Analyzing documents...\", \"step\": \"map\", \"progress\": 0.0}}\n\n"

            summaries = await self._map_summarize_documents(document_ids, total_docs, self._yield_progress)

            if not summaries:
                yield f"event: error\ndata: {{\"error\": \"No document summaries generated\"}}\n\n"
                return

            # REDUCE Phase: Combine summaries with prompt
            yield f"event: progress\ndata: {{\"message\": \"Generating final report...\", \"step\": \"reduce\", \"progress\": 0.9}}\n\n"

            final_report = await self._reduce_create_report(summaries, prompt)

            # Send final report
            yield f"event: report\ndata: {{\"content\": {self._escape_json(final_report)}}}\n\n"
            yield f"event: complete\ndata: {{\"message\": \"Report generation complete\"}}\n\n"

            logger.info(f"✅ Report generation completed: {len(final_report)} characters")

        except Exception as e:
            logger.error(f"❌ Report generation failed: {str(e)}")
            yield f"event: error\ndata: {{\"error\": \"{str(e)}\"}}\n\n"

    async def _yield_progress(self, current: int, total: int):
        """Helper to yield progress - not used in generator but kept for structure"""
        pass

    async def _map_summarize_documents(
        self,
        document_ids: List[str],
        total: int,
        progress_callback
    ) -> List[Dict[str, Any]]:
        """
        MAP Phase: Summarize each document in parallel with semaphore

        Args:
            document_ids: List of document IDs
            total: Total number of documents
            progress_callback: Callback for progress updates

        Returns:
            List of document summaries
        """
        logger.info(f"📊 MAP Phase: Summarizing {len(document_ids)} documents")

        # Semaphore to limit concurrent processing to 5
        semaphore = asyncio.Semaphore(5)

        async def summarize_one_document(doc_id: str, index: int) -> Dict[str, Any]:
            """Summarize a single document with semaphore"""
            async with semaphore:
                try:
                    # Query PostgreSQL for document
                    document = await self.postgres_client.find_document_by_id(doc_id)

                    if not document:
                        return {"document_id": doc_id, "summary": "Document not found", "success": False}

                    raw_content = document.get("raw_content", "")
                    filename = document.get("file_name", "Unknown")

                    if not raw_content:
                        return {"document_id": doc_id, "filename": filename, "summary": "No content found", "success": False}

                    # Ask LLM to summarize
                    summary_prompt = f"""Summarize this document comprehensively. Include:
- Main topics and themes
- Key findings and insights
- Important data, facts, or quotes
- Core concepts and ideas

Be thorough but concise. This summary will be used to generate a larger report.

Document: {filename}

Content:
{raw_content}"""

                    response = await self.llm.ainvoke(summary_prompt)
                    summary = response.content if hasattr(response, 'content') else str(response)

                    logger.info(f"✅ Summarized document {index + 1}/{total}: {filename}")

                    return {
                        "document_id": doc_id,
                        "filename": filename,
                        "summary": summary,
                        "success": True
                    }

                except Exception as e:
                    logger.error(f"❌ Failed to summarize document {doc_id}: {str(e)}")
                    return {"document_id": doc_id, "summary": str(e), "success": False}

        # Process all documents in parallel (MAP) with semaphore limiting to 5 concurrent
        tasks = [summarize_one_document(doc_id, i) for i, doc_id in enumerate(document_ids)]
        summaries = await asyncio.gather(*tasks)

        # Filter out failed summaries
        successful_summaries = [s for s in summaries if s.get("success")]
        logger.info(f"✅ MAP Phase complete: {len(successful_summaries)}/{len(document_ids)} documents summarized")

        return successful_summaries

    async def _reduce_create_report(self, summaries: List[Dict[str, Any]], user_prompt: str) -> str:
        """
        REDUCE Phase: Combine document summaries into final report using user's prompt

        Args:
            summaries: List of document summaries from MAP phase
            user_prompt: User's prompt specifying report structure and focus

        Returns:
            Final report as markdown string
        """
        logger.info(f"🔄 REDUCE Phase: Creating final report from {len(summaries)} summaries")

        # Combine all summaries with document references
        combined_summaries = "\n\n".join([
            f"## Document: {s['filename']}\n\n{s['summary']}"
            for s in summaries
        ])

        # Create final report prompt
        final_prompt = f"""{user_prompt}

Here are summaries of all the documents:

{combined_summaries}

Generate a comprehensive report following the format and structure specified in the prompt above.

IMPORTANT:
- Use markdown formatting for better readability
- Be thorough and detailed
- Structure the report with clear sections and headings
- Synthesize information across all documents, don't just list summaries"""

        response = await self.llm.ainvoke(final_prompt)
        final_report = response.content if hasattr(response, 'content') else str(response)

        logger.info(f"✅ REDUCE Phase complete: Generated {len(final_report)} character report")

        return final_report

    def _escape_json(self, text: str) -> str:
        """Escape text for JSON string"""
        import json
        return json.dumps(text)


# Singleton instance
_report_generator_service = None


def get_report_generator_service() -> ReportGeneratorService:
    """Get or create ReportGeneratorService singleton"""
    global _report_generator_service
    if _report_generator_service is None:
        _report_generator_service = ReportGeneratorService()
    return _report_generator_service
