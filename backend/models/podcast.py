"""
Podcast Pydantic Models (Scripting Phase)
Defines data structures for podcast script generation
"""

from pydantic import BaseModel, Field
from typing import List, Optional

class PodcastSegment(BaseModel):
    speaker: str = Field(description="Speaker label (e.g. 'Speaker 1', 'Speaker 2')")
    text: str = Field(description="The dialogue text spoken by the speaker")

class PodcastScript(BaseModel):
    title: str = Field(description="Title of the podcast episode")
    summary: str = Field(description="Brief summary of the episode content")
    segments: List[PodcastSegment] = Field(description="Ordered list of dialogue segments")



