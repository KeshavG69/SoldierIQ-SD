"""
Video Overview Pydantic Models
Request and storyboard models for narrated explainer videos
"""

from pydantic import BaseModel, Field
from typing import List, Literal, Optional


VideoFormat = Literal["explainer", "brief"]
VideoStyle = Literal["classic", "whiteboard", "watercolor", "papercraft", "retro_print", "tactical"]
VideoVoice = Literal["sarah", "brian", "george"]


class GenerateVideoOverviewRequest(BaseModel):
    """Request to generate a video overview from documents"""
    document_ids: List[str] = Field(..., description="Document IDs to build the video from")
    format: VideoFormat = Field(default="explainer")
    style: VideoStyle = Field(default="classic")
    voice: VideoVoice = Field(default="sarah")
    focus: Optional[str] = Field(default=None, max_length=500, description="Optional focus / custom instructions")
    # user_id and organization_id are extracted from JWT token by backend


class StoryboardScene(BaseModel):
    """One narrated scene of the video"""
    chapter: str = Field(description="Short chapter name for the video's chapter list (2-5 words)")
    narration: str = Field(description="What the narrator says over this scene, written to be spoken aloud")
    headline: str = Field(description="On-screen headline (3-8 words)")
    points: List[str] = Field(default_factory=list, description="0-3 very short on-screen points (2-6 words each)")
    stat_value: Optional[str] = Field(default=None, description="Optional key number/date shown large on screen, copied exactly from the source")
    stat_label: Optional[str] = Field(default=None, description="Label for the key number (2-5 words)")
    visual: str = Field(description="What the scene's illustration should depict (subject and composition, no text)")
    source: Optional[str] = Field(default=None, description="Filename of the main source document for this scene")


class Storyboard(BaseModel):
    """Complete video storyboard"""
    title: str = Field(description="Video title (max ~8 words)")
    subtitle: str = Field(description="One-line subtitle shown on the title scene")
    scenes: List[StoryboardScene] = Field(description="Scenes in order; the first introduces the topic, the last wraps up")
