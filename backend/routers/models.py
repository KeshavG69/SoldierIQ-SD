"""
Models API Endpoints
Returns list of available AI models for chat via OpenRouter
"""

from fastapi import APIRouter, Depends
from app.logger import logger
from auth.keycloak_auth import get_current_user_keycloak

router = APIRouter(tags=["models"])


@router.get("/models")
async def list_models(current_user: dict = Depends(get_current_user_keycloak)) -> dict:
    """
    List all available AI models for chat (OpenRouter aliases)

    Returns:
        Dict with list of available models
    """
    logger.info("Listing available models")

    models = [
        {
            "id": "google/gemini-3-pro-preview",
            "name": "Gemini 3 Pro"
        },
        {
            "id": "anthropic/claude-sonnet-4.5",
            "name": "Claude Sonnet 4.5"
        },
        {
            "id": "google/gemini-3-flash-preview",
            "name": "Gemini 3 Flash"
        },
        {
            "id": "google/gemini-2.5-pro",
            "name": "Gemini 2.5 Pro"
        },
        {
            "id": "anthropic/claude-haiku-4.5",
            "name": "Claude Haiku 4.5"
        }
    ]

    logger.info(f"✅ Returning {len(models)} models")

    return {
        "success": True,
        "models": models,
        "count": len(models)
    }
