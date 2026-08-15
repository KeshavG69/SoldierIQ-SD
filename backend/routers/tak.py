"""
TAK Configuration Router
Admin endpoints for configuring TAK server settings per organization
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import Optional

from auth.keycloak_auth import get_current_user_keycloak
from utils.tak_config_utils import (
    save_tak_config,
    get_tak_config,
    delete_tak_config,
    is_tak_enabled
)
from app.logger import logger

router = APIRouter(prefix="/tak", tags=["TAK Configuration"])


# ==================== REQUEST/RESPONSE MODELS ====================

class TAKConfigRequest(BaseModel):
    """Request model for creating/updating TAK configuration"""
    tak_enabled: bool = False
    tak_host: str = Field(..., description="TAK server hostname")
    tak_port: int = Field(default=8089, ge=1, le=65535)
    tak_username: str = Field(default="", description="TAK username (optional for public servers)")
    tak_password: str = Field(default="", description="TAK password (optional for public servers)")
    agent_callsign: str = Field(default="SoldierIQ-Agent")

    class Config:
        json_schema_extra = {
            "example": {
                "tak_enabled": True,
                "tak_host": "tak.company.com",
                "tak_port": 8089,
                "tak_username": "soldieriq-agent",
                "tak_password": "mypassword123",
                "agent_callsign": "SoldierIQ-Agent"
            }
        }


class TAKConfigResponse(BaseModel):
    """Response model for TAK configuration (excludes password)"""
    organization_id: str
    tak_enabled: bool
    tak_host: str
    tak_port: int
    tak_username: str
    agent_callsign: str

    class Config:
        json_schema_extra = {
            "example": {
                "organization_id": "123e4567-e89b-12d3-a456-426614174000",
                "tak_enabled": True,
                "tak_host": "tak.company.com",
                "tak_port": 8089,
                "tak_username": "soldieriq-agent",
                "agent_callsign": "SoldierIQ-Agent"
            }
        }


class TAKStatusResponse(BaseModel):
    """Response for TAK status check"""
    tak_configured: bool
    tak_enabled: bool


# ==================== ENDPOINTS ====================

@router.post("/config", response_model=TAKConfigResponse, status_code=status.HTTP_201_CREATED)
async def configure_tak(
    config: TAKConfigRequest,
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Configure TAK server settings for the organization.

    **Admin only** - Only organization admins can configure TAK settings.

    This creates or updates the TAK configuration for the entire organization.
    All users in the organization will use these settings when interacting with TAK.
    """
    try:
        # Get organization ID from current user
        organization_id = current_user.get("organization_id")

        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User must belong to an organization"
            )

        logger.info(f"Configuring TAK for organization: {organization_id}")

        # TODO: Add password encryption here before saving
        # For now, storing as plain text (should be encrypted in production!)

        # Save configuration (async call)
        config_id = await save_tak_config(
            organization_id=organization_id,
            tak_host=config.tak_host,
            tak_port=config.tak_port,
            tak_username=config.tak_username,
            tak_password=config.tak_password,  # TODO: Encrypt this!
            tak_enabled=config.tak_enabled,
            agent_callsign=config.agent_callsign
        )

        logger.info(f"✅ TAK configured successfully for org: {organization_id}")

        return TAKConfigResponse(
            organization_id=organization_id,
            tak_enabled=config.tak_enabled,
            tak_host=config.tak_host,
            tak_port=config.tak_port,
            tak_username=config.tak_username,
            agent_callsign=config.agent_callsign
        )

    except Exception as e:
        logger.error(f"❌ Failed to configure TAK: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to configure TAK: {str(e)}"
        )


@router.get("/config", response_model=TAKConfigResponse)
async def get_tak_configuration(
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Get TAK configuration for the organization.

    Returns the TAK settings (without password) for the current user's organization.
    """
    try:
        organization_id = current_user.get("organization_id")

        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User must belong to an organization"
            )

        config = await get_tak_config(organization_id)

        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TAK configuration not found for this organization"
            )

        return TAKConfigResponse(
            organization_id=organization_id,
            tak_enabled=config.get("tak_enabled", False),
            tak_host=config.get("tak_host", ""),
            tak_port=config.get("tak_port", 8089),
            tak_username=config.get("tak_username", ""),
            agent_callsign=config.get("agent_callsign", "SoldierIQ-Agent")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to get TAK config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get TAK configuration: {str(e)}"
        )


@router.get("/status", response_model=TAKStatusResponse)
async def get_tak_status(
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Check if TAK is configured and enabled for the organization.

    Returns a simple status indicating if TAK integration is available.
    """
    try:
        organization_id = current_user.get("organization_id")

        if not organization_id:
            return TAKStatusResponse(
                tak_configured=False,
                tak_enabled=False
            )

        config = await get_tak_config(organization_id)

        return TAKStatusResponse(
            tak_configured=config is not None,
            tak_enabled=config.get("tak_enabled", False) if config else False
        )

    except Exception as e:
        logger.error(f"❌ Failed to check TAK status: {e}")
        return TAKStatusResponse(
            tak_configured=False,
            tak_enabled=False
        )


@router.delete("/config", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tak_configuration(
    current_user: dict = Depends(get_current_user_keycloak)
):
    """
    Delete TAK configuration for the organization.

    **Admin only** - Removes all TAK settings for the organization.
    """
    try:
        organization_id = current_user.get("organization_id")

        if not organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User must belong to an organization"
            )

        success = await delete_tak_config(organization_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="TAK configuration not found"
            )

        logger.info(f"✅ TAK config deleted for org: {organization_id}")
        return None

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to delete TAK config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete TAK configuration: {str(e)}"
        )
