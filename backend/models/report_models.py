"""
Report Models
Pydantic models for API request payloads only
"""

from typing import Optional, List
from pydantic import BaseModel, Field


class SuggestFormatsRequest(BaseModel):
    """Request to trigger format suggestion generation (background task)"""
    document_ids: List[str] = Field(..., description="Document IDs to analyze")
    # user_id and organization_id are extracted from JWT token by backend


class GenerateReportRequest(BaseModel):
    """Request to generate a report"""
    document_ids: List[str] = Field(..., description="Document IDs to include in report")
    prompt: str = Field(..., description="Report generation prompt from frontend")
    # user_id and organization_id are extracted from JWT token by backend
