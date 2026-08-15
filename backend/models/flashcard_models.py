from pydantic import BaseModel, Field
from typing import List, Optional


class GenerateFlashcardsRequest(BaseModel):
    """Request to generate flashcards from documents"""
    document_ids: List[str] = Field(..., description="Document IDs to generate flashcards from")
    # user_id and organization_id are extracted from JWT token by backend
