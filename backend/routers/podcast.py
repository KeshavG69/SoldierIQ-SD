from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from services.podcast_service import get_podcast_service, PodcastService
from app.logger import logger

from clients.postgres_client import get_postgres_client
import uuid
from datetime import datetime
from auth.keycloak_auth import get_current_user_keycloak
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/podcasts", tags=["Podcasts"])

class PodcastGenerateRequest(BaseModel):
    document_ids: List[str]

class PodcastResponse(BaseModel):
    episode_id: str
    status: str
    message: str

@router.post("/generate", summary="Start podcast generation (Background Task)", response_model=PodcastResponse)
async def generate_podcast(
    request: PodcastGenerateRequest,
    background_tasks: BackgroundTasks,
    service: PodcastService = Depends(get_podcast_service),
    current_user: dict = Depends(get_current_context)
):
    """
    Start the podcast generation process in the background.
    Returns an episode_id to track progress.
    """
    try:
        # Extract organization_id and user_id from JWT token
        organization_id = current_user.get("organization_id")
        user_id = current_user.get("id")

        if not organization_id:
            raise HTTPException(status_code=400, detail="User must belong to an organization")

        logger.info(f"🎙️ Received podcast generation request for {len(request.document_ids)} documents (Org: {organization_id[:8]}...)")

        # Verify document IDs are not empty
        if not request.document_ids:
            raise HTTPException(status_code=400, detail="No document IDs provided")

        # Generate UUID for episode
        episode_id = str(uuid.uuid4())

        # Create initial PodcastEpisode record in PostgreSQL
        episode = {
            "id": episode_id,
            "organization_id": organization_id,
            "user_id": user_id,
            "document_ids": request.document_ids,
            "status": "processing",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        # Insert into PostgreSQL
        postgres = get_postgres_client()
        await postgres.insert_podcast(episode)

        # Add to background tasks
        background_tasks.add_task(
            service.generate_podcast,
            request.document_ids,
            organization_id,
            episode_id
        )
        
        return PodcastResponse(
            episode_id=episode_id,
            status="processing",
            message="Podcast generation started in background"
        )
        
    except Exception as e:
        logger.error(f"Error starting podcast generation: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {str(e)}")

@router.get("/{episode_id}", summary="Get podcast status/result")
async def get_podcast(
    episode_id: str,
    current_user: dict = Depends(get_current_context)
):
    """
    Get the status and result of a podcast generation task.
    """
    # Validate UUID
    try:
        uuid.UUID(episode_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Podcast ID format")

    # Extract user info from JWT token
    organization_id = current_user.get("organization_id")
    user_id = current_user.get("id")

    # Get from PostgreSQL
    postgres = get_postgres_client()
    podcast = await postgres.find_podcast(
        organization_id=organization_id,
        user_id=user_id,
        podcast_id=episode_id
    )

    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    return podcast
