"""
Reports Router - API endpoints for report generation
"""

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
import uuid

from models.report_models import GenerateReportRequest
from services.report_generator import get_report_generator_service
from app.logger import logger
from auth.keycloak_auth import get_current_user_keycloak
from orgs.dependencies import get_current_context


router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate")
async def generate_report(request: GenerateReportRequest, current_user: dict = Depends(get_current_context)):
    """
    Generate a report from documents using Map-Reduce with streaming

    This endpoint:
    1. Takes document IDs and a prompt (from frontend)
    2. Uses Map-Reduce to process documents in parallel
    3. Streams progress updates via Server-Sent Events
    4. Returns final report in markdown format

    Args:
        request: GenerateReportRequest with document_ids and prompt

    Returns:
        StreamingResponse with Server-Sent Events

    Example request:
    ```json
    {
        "document_ids": ["507f1f77bcf86cd799439011", "507f1f77bcf86cd799439012"],
        "prompt": "Create a technical guide with: 1) Overview, 2) Implementation, 3) Best Practices. Include source citations.",
        "model": "google/gemini-2.0-flash-exp:free",
        "user_id": "507f1f77bcf86cd799439013",
        "organization_id": "507f1f77bcf86cd799439014"
    }
    ```

    Server-Sent Events:
    ```
    event: start
    data: {"message": "Starting report generation"}

    event: progress
    data: {"message": "Analyzing documents...", "step": "map", "progress": 0.0}

    event: progress
    data: {"message": "Generating final report...", "step": "reduce", "progress": 0.9}

    event: report
    data: {"content": "# Report Title\\n\\n## Section 1..."}

    event: complete
    data: {"message": "Report generation complete"}
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

        # Validate prompt
        if not request.prompt or not request.prompt.strip():
            raise HTTPException(status_code=400, detail="Prompt cannot be empty")

        logger.info(f"📊 Report generation requested for {len(request.document_ids)} documents")

        generator_service = get_report_generator_service()

        # Return streaming response
        return StreamingResponse(
            generator_service.generate_report_stream(
                document_ids=request.document_ids,
                prompt=request.prompt,
                user_id=user_id,
                organization_id=organization_id
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"  # Disable nginx buffering
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate report: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate report: {str(e)}")
