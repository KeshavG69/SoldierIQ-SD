"""
TAK Configuration PostgreSQL Utilities
Functions for storing and fetching TAK configuration from PostgreSQL
"""

from typing import Optional, Dict, Any
from datetime import datetime
from clients.postgres_client import get_postgres_client
from app.logger import logger


async def save_tak_config(
    organization_id: str,
    tak_host: str,
    tak_port: int,
    tak_username: str,
    tak_password: str,
    tak_enabled: bool = True,
    agent_callsign: str = "SoldierIQ-Agent"
) -> str:
    """
    Save or update TAK configuration for an organization.

    Args:
        organization_id: Organization ID (UUID as string)
        tak_host: TAK server hostname
        tak_port: TAK server port
        tak_username: TAK username for authentication
        tak_password: TAK password (should be encrypted before passing)
        tak_enabled: Whether TAK is enabled
        agent_callsign: Agent's callsign on TAK network

    Returns:
        str: organization_id (configuration is upserted)
    """
    try:
        postgres_client = get_postgres_client()

        config_data = {
            "organization_id": organization_id,
            "tak_enabled": tak_enabled,
            "tak_host": tak_host,
            "tak_port": tak_port,
            "tak_username": tak_username,
            "tak_password": tak_password,
            "agent_callsign": agent_callsign,
            "updated_at": datetime.utcnow()
        }

        # Upsert (insert or update) TAK configuration
        await postgres_client.upsert_tak_config(config_data)
        logger.info(f"✅ Saved TAK config for org: {organization_id}")

        return organization_id

    except Exception as e:
        logger.error(f"❌ Failed to save TAK config: {e}")
        raise


async def get_tak_config(organization_id: str) -> Optional[Dict[str, Any]]:
    """
    Get TAK configuration for an organization.

    Args:
        organization_id: Organization ID (UUID as string)

    Returns:
        Dict with TAK config or None if not found
    """
    try:
        postgres_client = get_postgres_client()

        config = await postgres_client.get_tak_config(organization_id=organization_id)

        if config:
            logger.info(f"✅ Found TAK config for org: {organization_id}")
            return config
        else:
            logger.info(f"⚠️  No TAK config found for org: {organization_id}")
            return None

    except Exception as e:
        logger.error(f"❌ Failed to get TAK config: {e}")
        return None


async def delete_tak_config(organization_id: str) -> bool:
    """
    Delete TAK configuration for an organization.

    Args:
        organization_id: Organization ID (UUID as string)

    Returns:
        bool: True if deleted, False otherwise
    """
    try:
        postgres_client = get_postgres_client()

        deleted = await postgres_client.delete_tak_config(organization_id=organization_id)

        if deleted:
            logger.info(f"✅ Deleted TAK config for org: {organization_id}")
            return True
        else:
            logger.warning(f"⚠️  No TAK config found to delete for org: {organization_id}")
            return False

    except Exception as e:
        logger.error(f"❌ Failed to delete TAK config: {e}")
        return False


async def is_tak_enabled(organization_id: str) -> bool:
    """
    Check if TAK is enabled for an organization.

    Args:
        organization_id: Organization ID (UUID as string)

    Returns:
        bool: True if TAK is enabled, False otherwise
    """
    config = await get_tak_config(organization_id)
    return config.get("tak_enabled", False) if config else False


async def get_tak_credentials(organization_id: str) -> Optional[Dict[str, str]]:
    """
    Get TAK credentials for use in chat endpoint.

    Returns credentials needed to create TAK tools.

    Args:
        organization_id: Organization ID (UUID as string)

    Returns:
        Dict with tak_host, tak_port, tak_username, tak_password, agent_callsign
        or None if TAK not configured/enabled
    """
    config = await get_tak_config(organization_id)

    if not config or not config.get("tak_enabled", False):
        return None

    return {
        "tak_host": config.get("tak_host"),
        "tak_port": config.get("tak_port"),
        "tak_username": config.get("tak_username"),
        "tak_password": config.get("tak_password"),  # Already encrypted in DB
        "agent_callsign": config.get("agent_callsign", "SoldierIQ-Agent")
    }
