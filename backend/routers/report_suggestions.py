"""
Report Suggestions Router - API endpoints for AI-powered format suggestions
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
import uuid

from models.report_models import SuggestFormatsRequest
from services.format_suggester import get_format_suggester_service
from app.logger import logger
from auth.keycloak_auth import get_current_user_keycloak
from orgs.dependencies import get_current_context


router = APIRouter(prefix="/report-suggestions", tags=["report-suggestions"])


@router.post("/suggest-formats")
async def suggest_formats(request: SuggestFormatsRequest, background_tasks: BackgroundTasks, current_user: dict = Depends(get_current_context)):
    """
    Trigger background task to generate format suggestions

    This endpoint:
    1. Checks if suggestions already exist for these documents
    2. If yes, returns existing workflow_id
    3. If no, creates new workflow and triggers background task

    Frontend should poll /report-suggestions/get-suggestions with document_ids to check status

    Args:
        request: SuggestFormatsRequest with document_ids

    Returns:
        workflow_id for tracking

    Example request:
    ```json
    {
        "document_ids": ["507f1f77bcf86cd799439011", "507f1f77bcf86cd799439012"],
        "user_id": "507f1f77bcf86cd799439013",
        "organization_id": "507f1f77bcf86cd799439014"
    }
    ```

    Example response:
    ```json
    {
        "workflow_id": "507f1f77bcf86cd799439015",
        "status": "processing",
        "message": "Format suggestions generation started"
    }
    ```
    """
    try:
        # Extract user_id and organization_id from JWT token
        user_id = current_user.get("id")
        organization_id = current_user.get("organization_id")

        # Validate all document_ids are UUIDs
        for doc_id in request.document_ids:
            try:
                uuid.UUID(doc_id)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid document_id format: {doc_id}"
                )

        # Validate organization_id format
        if organization_id:
            try:
                uuid.UUID(organization_id)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid organization_id format: {organization_id}")

        logger.info(f"📊 Format suggestions requested for {len(request.document_ids)} documents")

        suggester_service = get_format_suggester_service()

        # Get or create suggestions workflow
        workflow_id = await suggester_service.get_or_create_suggestions(
            document_ids=request.document_ids,
            user_id=user_id,
            organization_id=organization_id
        )

        # Trigger background task (won't run if already exists)
        background_tasks.add_task(
            suggester_service.generate_suggestions_background,
            workflow_id=workflow_id,
            document_ids=request.document_ids,
            user_id=user_id,
            organization_id=organization_id
        )

        return {
            "workflow_id": workflow_id,
            "status": "processing",
            "message": "Format suggestions generation started"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to trigger format suggestions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to trigger format suggestions: {str(e)}")


@router.post("/get-suggestions")
async def get_suggestions(request: SuggestFormatsRequest, current_user: dict = Depends(get_current_context)):
    """
    Get format suggestions for documents (frontend polling endpoint)

    Frontend calls this endpoint to check the status of format suggestions.

    Args:
        request: Document IDs to get suggestions for

    Returns:
        status: "not_found", "processing", "completed", or "failed"
        suggestions: List of format suggestions (when completed)

    Example request:
    ```json
    {
        "document_ids": ["507f1f77bcf86cd799439011", "507f1f77bcf86cd799439012"]
    }
    ```

    Example response (processing):
    ```json
    {
        "status": "processing",
        "suggestions": null
    }
    ```

    Example response (completed):
    ```json
    {
        "status": "completed",
        "suggestions": [
            {
                "name": "Kubernetes Deployment Guide",
                "description": "Step-by-step guide for deploying applications",
                "prompt": "Create a deployment guide with: 1) Prerequisites, 2) Installation steps, 3) Configuration, 4) Best practices"
            }
        ],
        "created_at": "2024-02-06T10:30:00Z",
        "updated_at": "2024-02-06T10:31:00Z"
    }
    ```
    """
    try:
        # Validate all document_ids are UUIDs
        for doc_id in request.document_ids:
            try:
                uuid.UUID(doc_id)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid document_id format: {doc_id}"
                )

        logger.info(f"🔍 Getting suggestions for {len(request.document_ids)} documents")

        suggester_service = get_format_suggester_service()
        result = await suggester_service.get_suggestions_by_documents(document_ids=request.document_ids)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get suggestions: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get suggestions: {str(e)}")
