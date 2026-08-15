"""
Flashcards API Router
Endpoints for generating flashcards from documents
"""

from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any

from models.flashcard_models import GenerateFlashcardsRequest
from services.flashcard_generator import get_flashcard_generator_service
from app.logger import logger
from auth.keycloak_auth import get_current_user_keycloak
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/flashcards", tags=["flashcards"])


@router.post("/generate")
async def generate_flashcards(request: GenerateFlashcardsRequest, current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    Generate flashcards from documents using Map-Reduce

    Args:
        request: Flashcard generation request with document IDs

    Returns:
        Dict with flashcard data (title, cards, workflow_id)
    """
    try:
        # Extract user_id and organization_id from JWT token
        user_id = current_user.get("id")
        organization_id = current_user.get("organization_id")

        logger.info(f"📝 Flashcard generation request for {len(request.document_ids)} documents")

        # Validate document IDs
        if not request.document_ids:
            raise HTTPException(status_code=400, detail="No document IDs provided")

        # Get service and generate flashcards
        generator_service = get_flashcard_generator_service()
        flashcard_data = await generator_service.generate_flashcards(
            document_ids=request.document_ids,
            user_id=user_id,
            organization_id=organization_id
        )

        return {
            "status": "success",
            "data": flashcard_data
        }

    except Exception as e:
        logger.error(f"❌ Flashcard generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
