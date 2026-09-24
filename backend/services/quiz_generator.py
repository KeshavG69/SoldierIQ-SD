"""
Quiz Generator Service
Generates multiple-choice quizzes using Map-Reduce pattern
"""

import asyncio
import random
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from clients.postgres_client import get_postgres_client
from clients.ultimate_llm import get_llm
from models.quiz_models import Quiz, QUESTION_COUNTS
from utils.text_match import normalize_text, quote_in_text
from app.logger import logger


DIFFICULTY_GUIDANCE = {
    "easy": "Test recall of explicitly stated facts, definitions and key terms. Wrong options should be clearly wrong to someone who read the material.",
    "medium": "Mix recall with comprehension: ask why/how things work and how concepts relate. Wrong options should be plausible and drawn from the same domain.",
    "hard": "Test application, analysis and synthesis across concepts (scenarios, implications, comparisons). Wrong options should be highly plausible and reflect common misconceptions.",
}


class QuizGeneratorService:
    """Service for generating quizzes using Map-Reduce"""

    def __init__(self):
        """Initialize quiz generator service"""
        self.postgres_client = get_postgres_client()
        self.llm = get_llm(model="google/gemini-3-flash-preview", provider="openrouter")
        self.structured_llm = self.llm.with_structured_output(Quiz)

    async def generate_quiz(
        self,
        document_ids: List[str],
        question_count: str = "standard",
        difficulty: str = "medium",
        topic: Optional[str] = None,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate a quiz using Map-Reduce pattern

        MAP Phase: Extract testable facts (with verbatim quotes) from each document
        REDUCE Phase: Write multiple-choice questions with hints and per-option rationales,
                      then verify each question's evidence quote against the source text

        Returns:
            Dict with quiz data including title and questions
        """
        try:
            num_questions = QUESTION_COUNTS.get(question_count, QUESTION_COUNTS["standard"])
            logger.info(
                f"❓ Starting quiz generation for {len(document_ids)} documents "
                f"({num_questions} questions, {difficulty}, topic={topic!r})"
            )

            # MAP Phase: Extract testable facts from each document
            extracted = await self._map_extract_facts(document_ids, topic)

            if not extracted:
                raise Exception("No content extracted from documents")

            # REDUCE Phase: Generate questions and title
            quiz_data = await self._reduce_create_quiz(extracted, num_questions, difficulty, topic)

            logger.info(f"✅ Quiz generation completed: {len(quiz_data['questions'])} questions")

            settings = {"question_count": question_count, "difficulty": difficulty, "topic": topic}
            workflow_id = await self._save_to_workflows(
                document_ids=document_ids,
                quiz_data=quiz_data,
                settings=settings,
                user_id=user_id,
                organization_id=organization_id
            )

            quiz_data["workflow_id"] = str(workflow_id)
            quiz_data["document_count"] = len(document_ids)
            quiz_data["question_count"] = len(quiz_data["questions"])
            quiz_data["settings"] = settings
            return quiz_data

        except Exception as e:
            logger.error(f"❌ Quiz generation failed: {str(e)}")
            raise

    async def _map_extract_facts(self, document_ids: List[str], topic: Optional[str]) -> List[Dict[str, Any]]:
        """
        MAP Phase: Extract testable facts from each document in parallel
        """
        semaphore = asyncio.Semaphore(5)
        focus = f"\nFocus especially on content related to: {topic}\n" if topic else ""

        async def extract_from_one_document(doc_id: str) -> Dict[str, Any]:
            async with semaphore:
                try:
                    document = await self.postgres_client.find_document_by_id(doc_id)

                    if not document:
                        logger.warning(f"⚠️ Document {doc_id} not found")
                        return {"document_id": doc_id, "facts": "", "success": False}

                    filename = document.get("file_name", "Unknown")
                    raw_content = document.get("raw_content", "")

                    if not raw_content:
                        logger.warning(f"⚠️ Document {doc_id} has no content")
                        return {"document_id": doc_id, "filename": filename, "facts": "", "success": False}

                    extraction_prompt = f"""Analyze this document and extract the material that would make good multiple-choice quiz questions: key facts, definitions, figures, dates, procedures, cause-and-effect relationships, comparisons, and easily confused concepts.
{focus}
For each item:
- State the fact precisely and self-contained, so a question can be written from it without seeing the document.
- Follow it with the supporting sentence copied EXACTLY, word for word, from the document, on its own line as: Quote: "..."

Document content:
{raw_content}"""

                    response = await self.llm.ainvoke(extraction_prompt)
                    facts = response.content if hasattr(response, 'content') else str(response)

                    logger.info(f"✅ Extracted quiz material from: {filename}")

                    return {
                        "document_id": doc_id,
                        "filename": filename,
                        "facts": facts,
                        "normalized_content": normalize_text(raw_content),
                        "success": True
                    }

                except Exception as e:
                    logger.error(f"❌ Failed to extract quiz material from {doc_id}: {str(e)}")
                    return {"document_id": doc_id, "facts": "", "success": False, "error": str(e)}

        tasks = [extract_from_one_document(doc_id) for doc_id in document_ids]
        results = await asyncio.gather(*tasks)

        successful_results = [r for r in results if r.get("success", False)]
        logger.info(f"📊 Extracted quiz material from {len(successful_results)}/{len(document_ids)} documents")
        return successful_results

    async def _reduce_create_quiz(
        self,
        extracted: List[Dict[str, Any]],
        num_questions: int,
        difficulty: str,
        topic: Optional[str]
    ) -> Dict[str, Any]:
        """
        REDUCE Phase: Generate multiple-choice questions and title from extracted facts
        """
        combined_facts = "\n\n".join([
            f"Document: {e.get('filename', 'Unknown')}\n{e['facts']}"
            for e in extracted
        ])
        focus = f"\n- Focus the questions on: {topic}" if topic else ""

        quiz_prompt = f"""You are writing a multiple-choice quiz to test someone's understanding of the source material below.

REQUIREMENTS:
- Write exactly {num_questions} questions.
- Difficulty: {difficulty.upper()}. {DIFFICULTY_GUIDANCE.get(difficulty, DIFFICULTY_GUIDANCE['medium'])}{focus}
- Each question has exactly 4 options and exactly ONE correct option (is_correct=true).
- Every option needs a rationale (1-2 sentences) explaining why it is correct or why it is wrong, grounded in the source material.
- Give each question a short hint that points toward the answer without revealing it.
- Set "source" to the document filename the question is based on.
- Set "evidence" to the supporting Quote for the correct answer, copied exactly as it appears in the source material.
- Base every question strictly on the source material; do not use outside knowledge.
- Test one idea per question. Spread questions across different concepts and across all documents; do not ask the same thing twice.
- Keep options similar in length and style so the correct one does not stand out. Never use "All of the above" or "None of the above".
- Give the quiz a short descriptive title based on the main topic.

Source material:
{combined_facts}"""

        quiz: Quiz = await self.structured_llm.ainvoke(quiz_prompt)

        content_by_filename = {e.get("filename"): e["normalized_content"] for e in extracted}
        verified, unverified = [], []

        for q in quiz.questions:
            if len(q.options) < 2 or sum(1 for o in q.options if o.is_correct) != 1:
                logger.warning(f"⚠️ Dropping quiz question without exactly one correct option: {q.question[:80]}")
                continue

            q_dict = q.model_dump()
            # LLMs tend to favour certain answer positions; shuffle so the correct one is evenly spread
            random.shuffle(q_dict["options"])

            # Verify the evidence quote against the cited document, falling back to any selected document
            source_content = content_by_filename.get(q.source)
            candidates = [source_content] if source_content else list(content_by_filename.values())
            if any(quote_in_text(q.evidence, content) for content in candidates):
                verified.append(q_dict)
            else:
                q_dict["evidence"] = None
                unverified.append(q_dict)

        logger.info(f"🔎 Evidence check: {len(verified)} verified, {len(unverified)} unverified questions")

        # Prefer grounded questions; only keep unverified ones if dropping them would gut the quiz
        questions = verified
        if len(verified) < max(1, num_questions // 2):
            logger.warning("⚠️ Too few questions passed the evidence check; keeping unverified questions")
            questions = verified + unverified

        if not questions:
            raise Exception("Quiz generation produced no valid questions")

        logger.info(f"✅ Generated {len(questions)} quiz questions with title: {quiz.title}")
        return {"title": quiz.title, "questions": questions[:num_questions]}

    async def _save_to_workflows(
        self,
        document_ids: List[str],
        quiz_data: Dict[str, Any],
        settings: Dict[str, Any],
        user_id: Optional[str],
        organization_id: Optional[str]
    ) -> str:
        """
        Save quiz to workflows table in PostgreSQL
        """
        workflow_id = str(uuid.uuid4())

        workflow_doc = {
            "id": workflow_id,
            "type": "quiz",
            "document_ids": document_ids,
            "user_id": user_id,
            "organization_id": organization_id,
            "status": "completed",
            "data": {
                "title": quiz_data["title"],
                "questions": quiz_data["questions"],
                "question_count": len(quiz_data["questions"]),
                "document_count": len(document_ids),
                "settings": settings
            },
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }

        await self.postgres_client.insert_workflow(workflow_doc)

        logger.info(f"✅ Saved quiz to workflows: {workflow_id}")
        return workflow_id

    async def list_quizzes(self, user_id: str, organization_id: str) -> List[Dict[str, Any]]:
        """List the user's saved quizzes (summaries only, newest first)"""
        # Question bodies are stripped in SQL; only the summary fields come back
        workflows = await self.postgres_client.find_workflow_summaries_by_user(
            "quiz", user_id, organization_id, exclude_data_keys=["questions"]
        )
        return [
            {
                "workflow_id": w["id"],
                "title": w["data"].get("title", "Quiz"),
                "question_count": w["data"].get("question_count", 0),
                "document_count": w["data"].get("document_count", w.get("document_count") or 0),
                "settings": w["data"].get("settings", {}),
                "created_at": w["created_at"].isoformat() if w.get("created_at") else None,
            }
            for w in workflows
        ]

    async def get_quiz(self, workflow_id: str, user_id: str, organization_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Fetch a saved quiz, only if it belongs to the requesting user and organization"""
        workflow = await self.postgres_client.find_workflow_by_id(workflow_id, "quiz")
        if not workflow or workflow.get("user_id") != user_id or workflow.get("organization_id") != organization_id:
            return None

        data = workflow["data"]
        return {
            **data,
            "workflow_id": workflow["id"],
            "document_count": data.get("document_count", len(workflow.get("document_ids") or [])),
            "question_count": data.get("question_count", len(data.get("questions", []))),
        }


# Singleton instance
_quiz_generator_service = None


def get_quiz_generator_service() -> QuizGeneratorService:
    """Get or create quiz generator service singleton"""
    global _quiz_generator_service
    if _quiz_generator_service is None:
        _quiz_generator_service = QuizGeneratorService()
    return _quiz_generator_service
