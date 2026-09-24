"""
Slide Deck Pydantic Models
"""

from pydantic import BaseModel, Field
from typing import List, Literal, Optional


DeckFormat = Literal["detailed", "presenter"]
DeckLength = Literal["short", "default", "long"]
DeckStyle = Literal["auto", "professional", "tactical", "editorial", "instructional", "sketch"]


class GenerateSlideDeckRequest(BaseModel):
    """Request to generate a slide deck from documents"""
    document_ids: List[str] = Field(..., description="Document IDs to build the deck from")
    format: DeckFormat = Field(default="detailed")
    length: DeckLength = Field(default="default")
    style: DeckStyle = Field(default="auto")
    focus: Optional[str] = Field(default=None, max_length=500, description="Optional focus / custom instructions")
    # user_id and organization_id are extracted from JWT token by backend
