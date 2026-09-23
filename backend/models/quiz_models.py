"""
Quiz Pydantic Models
Request and structured-output models for quiz generation (NotebookLM-style)
"""

from pydantic import BaseModel, Field
from typing import List, Literal, Optional


QuestionCount = Literal["fewer", "standard", "more"]
Difficulty = Literal["easy", "medium", "hard"]

# How many questions each count option maps to
QUESTION_COUNTS = {"fewer": 5, "standard": 10, "more": 20}


class GenerateQuizRequest(BaseModel):
    """Request to generate a quiz from documents"""
    document_ids: List[str] = Field(..., description="Document IDs to generate the quiz from")
    question_count: QuestionCount = Field(default="standard", description="Number of questions")
    difficulty: Difficulty = Field(default="medium", description="Question difficulty")
    topic: Optional[str] = Field(default=None, max_length=500, description="Optional focus topic")
    # user_id and organization_id are extracted from JWT token by backend


class AnswerOption(BaseModel):
    """A single multiple-choice option"""
    text: str = Field(description="The answer option text")
    is_correct: bool = Field(description="True for the single correct option")
    rationale: str = Field(
        description="1-2 sentences explaining why this option is correct or incorrect, grounded in the source"
    )


class QuizQuestion(BaseModel):
    """A multiple-choice question with exactly one correct answer"""
    question: str = Field(description="The question text")
    options: List[AnswerOption] = Field(description="Exactly 4 answer options")
    hint: str = Field(description="A short hint that nudges toward the answer without giving it away")
    source: str = Field(description="Filename of the source document the question is based on")
    evidence: str = Field(
        description="A short verbatim quote (one sentence) copied exactly from the source material that supports the correct answer"
    )


class Quiz(BaseModel):
    """Complete quiz produced by the LLM"""
    title: str = Field(description="Short descriptive title for the quiz, e.g. 'Supply Chain Logistics Quiz'")
    questions: List[QuizQuestion] = Field(description="The quiz questions")
