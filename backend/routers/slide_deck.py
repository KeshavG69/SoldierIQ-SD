"""
Slide Deck API Router
Endpoints for generating and retrieving slide decks

Generation runs as a background task: POST returns a workflow_id immediately and the
frontend polls GET /slide-deck/{workflow_id} until status is "completed" or "failed".
"""

import uuid
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any, List

from models.slide_deck_models import GenerateSlideDeckRequest
from services.slide_deck_generator import get_slide_deck_generator_service
from app.logger import logger
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/slide-deck", tags=["slide-deck"])


def _validate_uuid(value: str, name: str) -> None:
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {name}: {value}")


async def _start_generation(
    document_ids: List[str],
    options: Dict[str, Any],
    current_user: dict,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")
    if not user_id or not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")

    service = get_slide_deck_generator_service()
    workflow_id = await service.create_pending(document_ids, options, user_id, organization_id)
    background_tasks.add_task(service.run_generation, workflow_id, document_ids, options, organization_id)

    return {
        "status": "success",
        "data": {"workflow_id": workflow_id, "status": "processing"}
    }


@router.post("/generate")
async def generate_deck(
    request: GenerateSlideDeckRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    """
    Start generating a slide deck from documents (runs in the background)

    Returns:
        Dict with workflow_id to poll
    """
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided")
    for doc_id in request.document_ids:
        _validate_uuid(doc_id, "document id")

    logger.info(f"📝 Slide deck generation request for {len(request.document_ids)} documents")

    options = {
        "format": request.format,
        "length": request.length,
        "style": request.style,
        "focus": (request.focus or "").strip() or None,
    }
    try:
        return await _start_generation(request.document_ids, options, current_user, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to start slide deck generation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: /list must be declared before /{workflow_id} so it isn't captured by the ID route
@router.get("/list")
async def list_decks(current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    List the current user's slide decks (newest first), including in-progress ones
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")
    if not user_id or not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")

    try:
        decks = await get_slide_deck_generator_service().list_decks(user_id, organization_id)
        return {
            "status": "success",
            "data": decks
        }
    except Exception as e:
        logger.error(f"❌ Failed to list slide decks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}")
async def get_deck(workflow_id: str, current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    Get a slide deck's status and, once completed, its image URLs
    """
    _validate_uuid(workflow_id, "deck id")

    try:
        deck = await get_slide_deck_generator_service().get_deck(
            workflow_id,
            user_id=current_user.get("id"),
            organization_id=current_user.get("organization_id")
        )
    except Exception as e:
        logger.error(f"❌ Failed to get slide deck: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    if not deck:
        raise HTTPException(status_code=404, detail="Slide deck not found")

    return {
        "status": "success",
        "data": deck
    }


@router.post("/{workflow_id}/regenerate")
async def regenerate_deck(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    """
    Generate a new slide deck with the same documents and settings as an existing one
    """
    _validate_uuid(workflow_id, "deck id")

    service = get_slide_deck_generator_service()
    existing = await service.get_deck(
        workflow_id,
        user_id=current_user.get("id"),
        organization_id=current_user.get("organization_id")
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Slide deck not found")

    try:
        return await _start_generation(existing["document_ids"], existing["settings"], current_user, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to regenerate slide deck: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
