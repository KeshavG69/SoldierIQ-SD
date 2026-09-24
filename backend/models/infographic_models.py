"""
Infographic Pydantic Models
Request, map-phase digest and reduce-phase spec models for infographic generation
"""

from pydantic import BaseModel, Field
from typing import List, Literal, Optional


Orientation = Literal["portrait", "landscape", "square"]
DetailLevel = Literal["concise", "standard", "detailed"]
Style = Literal["auto", "professional", "tactical", "editorial", "instructional", "sketch"]

# Image aspect ratio per orientation
ASPECT_RATIOS = {"portrait": "3:4", "landscape": "16:9", "square": "1:1"}

# Content budget per detail level
DETAIL_BUDGETS = {
    "concise": {"sections": "3-4", "items": "about 6", "words": 60},
    "standard": {"sections": "4-5", "items": "about 10", "words": 120},
    "detailed": {"sections": "6-7", "items": "about 15", "words": 200},
}


class GenerateInfographicRequest(BaseModel):
    """Request to generate an infographic from documents"""
    document_ids: List[str] = Field(..., description="Document IDs to generate the infographic from")
    orientation: Orientation = Field(default="portrait")
    detail_level: DetailLevel = Field(default="standard")
    style: Style = Field(default="auto")
    focus: Optional[str] = Field(default=None, max_length=500, description="Optional focus / custom instructions")
    # user_id and organization_id are extracted from JWT token by backend


# ---------------------------------------------------------------------------
# MAP phase: per-document ranked digest
# ---------------------------------------------------------------------------

InsightKind = Literal["stat", "step", "comparison", "timeline", "risk", "recommendation", "definition"]


class Insight(BaseModel):
    """A candidate piece of content for the infographic"""
    claim: str = Field(description="Short, self-contained statement of the insight")
    kind: InsightKind = Field(description="What kind of content this is")
    value: Optional[str] = Field(default=None, description="The key number/date/quantity if any, e.g. '72 hrs', '3 of 5 units'")
    quote: str = Field(description="The supporting sentence copied EXACTLY, word for word, from the document")
    importance: int = Field(description="Importance from 1 (minor detail) to 5 (central to the document's purpose)")
    why: str = Field(description="One line on why this matters")


class DocDigest(BaseModel):
    """Ranked digest of one document"""
    main_point: str = Field(description="The document's single most important takeaway, in one sentence")
    insights: List[Insight] = Field(description="Up to 15 candidate insights, most important first")


# ---------------------------------------------------------------------------
# REDUCE phase: the infographic spec
# ---------------------------------------------------------------------------

SectionKind = Literal["stats", "list", "steps", "comparison", "timeline"]


class SpecItem(BaseModel):
    """A single item within a section"""
    label: str = Field(description="Short label (2-6 words)")
    value: Optional[str] = Field(default=None, description="Headline number/date if any, copied exactly from the source")
    description: Optional[str] = Field(default=None, description="Optional one short line of supporting text")
    icon_hint: str = Field(description="A simple icon concept for this item, e.g. 'fuel can', 'clock', 'shield'")
    source: str = Field(description="Filename of the document this item comes from")


class SpecSection(BaseModel):
    """A section of the infographic"""
    heading: str = Field(description="Section heading (2-5 words)")
    kind: SectionKind = Field(description="How the section should be visualized")
    items: List[SpecItem] = Field(description="Items in this section")


class InfographicSpec(BaseModel):
    """Complete infographic content plan"""
    title: str = Field(description="Infographic title (max ~8 words), states the headline takeaway")
    subtitle: str = Field(description="One-line subtitle giving context")
    sections: List[SpecSection] = Field(description="Sections in reading order")
    takeaway: Optional[str] = Field(default=None, description="Optional bottom-line sentence for the footer banner")
