"""
Quiz API Router
Endpoints for generating and retrieving quizzes
"""

import uuid
from fastapi import APIRouter, HTTPException, Depends
from typing import Dict, Any

from models.quiz_models import GenerateQuizRequest
from services.quiz_generator import get_quiz_generator_service
from app.logger import logger
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/generate")
async def generate_quiz(request: GenerateQuizRequest, current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    Generate a multiple-choice quiz from documents using Map-Reduce

    Args:
        request: Quiz generation request with document IDs and options

    Returns:
        Dict with quiz data (title, questions, workflow_id)
    """
    if not request.document_ids:
        raise HTTPException(status_code=400, detail="No document IDs provided")

    try:
        user_id = current_user.get("id")
        organization_id = current_user.get("organization_id")

        logger.info(f"📝 Quiz generation request for {len(request.document_ids)} documents")

        generator_service = get_quiz_generator_service()
        quiz_data = await generator_service.generate_quiz(
            document_ids=request.document_ids,
            question_count=request.question_count,
            difficulty=request.difficulty,
            topic=(request.topic or "").strip() or None,
            user_id=user_id,
            organization_id=organization_id
        )

        return {
            "status": "success",
            "data": quiz_data
        }

    except Exception as e:
        logger.error(f"❌ Quiz generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: /list must be declared before /{workflow_id} so it isn't captured by the ID route
@router.get("/list")
async def list_quizzes(current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    List the current user's saved quizzes (newest first)
    """
    user_id = current_user.get("id")
    organization_id = current_user.get("organization_id")

    if not user_id or not organization_id:
        raise HTTPException(status_code=400, detail="User must belong to an organization")

    try:
        quizzes = await get_quiz_generator_service().list_quizzes(user_id, organization_id)
        return {
            "status": "success",
            "data": quizzes
        }
    except Exception as e:
        logger.error(f"❌ Failed to list quizzes: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{workflow_id}")
async def get_quiz(workflow_id: str, current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    """
    Get a saved quiz by ID
    """
    try:
        uuid.UUID(workflow_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid quiz id: {workflow_id}")

    try:
        quiz = await get_quiz_generator_service().get_quiz(
            workflow_id,
            user_id=current_user.get("id"),
            organization_id=current_user.get("organization_id")
        )
    except Exception as e:
        logger.error(f"❌ Failed to get quiz: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    return {
        "status": "success",
        "data": quiz
    }
