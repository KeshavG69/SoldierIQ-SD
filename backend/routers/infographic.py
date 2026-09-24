"""
Infographic API Router
Endpoints for generating and retrieving infographics

Generation runs as a background task: POST returns a workflow_id immediately and the
frontend polls GET /infographic/{workflow_id} until status is "completed" or "failed".
"""

import uuid
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from typing import Dict, Any, List

from models.infographic_models import GenerateInfographicRequest
from services.infographic_generator import get_infographic_generator_service
from app.logger import logger
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/infographic", tags=["infographic"])


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

    service = get_infographic_generator_service()
    workflow_id = await service.create_pending(document_ids, options, user_id, organization_id)
    background_tasks.add_task(service.run_generation, workflow_id, document_ids, options, organization_id)

    return {
        "status": "success",
        "data": {"workflow_id": workflow_id, "status": "processing"}
    }


@router.post("/generate")
async def generate_infographic(
    request: GenerateInfographicRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    """
    Start generating an infographic from documents (runs in the background)

    Returns:
        Dict with workflow_id to poll
    """
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided")
    for doc_id in request.document_ids:
        _validate_uuid(doc_id, "document id")

    logger.info(f"📝 Infographic generation request for {len(request.document_ids)} documents")

    options = {
        "orientation": request.orientation,
        "detail_level": request.detail_level,
        "style": request.style,
        "focus": (request.focus or "").strip() or None,
    }
    try:
        return await _start_generation(request.document_ids, options, current_user, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to start infographic generation: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: /list must be declared before /{workflow_id} so it isn't captured by the ID route
@router.get("/list")
async def list_infographics(current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    List the current user's infographics (newest first), including in-progress ones
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")
    if not user_id or not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")

    try:
        infographics = await get_infographic_generator_service().list_infographics(user_id, organization_id)
        return {
            "status": "success",
            "data": infographics
        }
    except Exception as e:
        logger.error(f"❌ Failed to list infographics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}")
async def get_infographic(workflow_id: str, current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    Get an infographic's status and, once completed, its image URLs
    """
    _validate_uuid(workflow_id, "infographic id")

    try:
        infographic = await get_infographic_generator_service().get_infographic(
            workflow_id,
            user_id=current_user.get("id"),
            organization_id=current_user.get("organization_id")
        )
    except Exception as e:
        logger.error(f"❌ Failed to get infographic: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    if not infographic:
        raise HTTPException(status_code=404, detail="Infographic not found")

    return {
        "status": "success",
        "data": infographic
    }


@router.post("/{workflow_id}/regenerate")
async def regenerate_infographic(
    workflow_id: str,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    """
    Generate a new infographic with the same documents and settings as an existing one
    """
    _validate_uuid(workflow_id, "infographic id")

    service = get_infographic_generator_service()
    existing = await service.get_infographic(
        workflow_id,
        user_id=current_user.get("id"),
        organization_id=current_user.get("organization_id")
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Infographic not found")

    try:
        return await _start_generation(existing["document_ids"], existing["settings"], current_user, background_tasks)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to regenerate infographic: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
