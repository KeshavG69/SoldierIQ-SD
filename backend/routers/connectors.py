"""
App connectors (Composio) — connect third-party apps the chat agent can act in.

Endpoints
---------
GET   /api/connectors             Apps + their actions, with this user's connection
                                  status and on/off toggles (+ total_enabled/limit).
POST  /api/connectors/connect     Start OAuth for one app; returns the auth URL.
POST  /api/connectors/callback    OAuth landed back; confirm with Composio, mark ACTIVE.
POST  /api/connectors/disconnect  Revoke the Composio account, drop our record,
                                  switch the app and its actions off.
POST  /api/connectors/toggle      Switch an app (tool_id) or one action (action_id)
                                  on/off for this user.

Everything is per user within the active organization. The chat agent gets
only the enabled actions of enabled, connected apps (services/chat.py).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.logger import logger
from clients.composio_connectors import (
    ComposioConnectorError,
    confirm_connection,
    disconnect,
    initiate_connection,
    list_connectors,
    set_action_enabled,
    set_tool_enabled,
)
from orgs.dependencies import get_current_context

router = APIRouter(prefix="/connectors", tags=["connectors"])


def _ids(current_user: dict) -> tuple[Optional[str], str]:
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(status_code=400, detail="User missing id")
    return current_user.get("organization_id"), user_id


@router.get("")
async def get_connectors(current_user: dict = Depends(get_current_context)) -> Dict[str, Any]:
    org_id, user_id = _ids(current_user)
    return await list_connectors(org_id, user_id)


class ConnectRequest(BaseModel):
    service: str
    # Where Composio sends the browser after consent. The frontend passes
    # `${origin}/oauth-callback?connector=<service>`.
    callback_url: Optional[str] = Field(default=None)


@router.post("/connect")
async def connect(
    body: ConnectRequest, current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    org_id, user_id = _ids(current_user)
    try:
        return await initiate_connection(org_id, user_id, body.service, body.callback_url)
    except ComposioConnectorError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # pragma: no cover - Composio surface
        logger.error(f"Connector connect failed ({body.service}): {e}")
        raise HTTPException(status_code=502, detail=f"Composio error: {e}")


class CallbackRequest(BaseModel):
    connected_account_id: str


@router.post("/callback")
async def callback(
    body: CallbackRequest, current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    org_id, user_id = _ids(current_user)
    result = await confirm_connection(org_id, user_id, body.connected_account_id)
    if not result:
        raise HTTPException(status_code=404, detail="Connection not found")
    return result


class DisconnectRequest(BaseModel):
    service: str


@router.post("/disconnect")
async def disconnect_endpoint(
    body: DisconnectRequest, current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    org_id, user_id = _ids(current_user)
    removed = await disconnect(org_id, user_id, body.service)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{body.service} is not connected")
    return {"success": True, "service": body.service}


class ToggleRequest(BaseModel):
    # Exactly one of tool_id / action_id.
    tool_id: Optional[str] = None
    action_id: Optional[str] = None
    enabled: bool


@router.post("/toggle")
async def toggle(
    body: ToggleRequest, current_user: dict = Depends(get_current_context)
) -> Dict[str, Any]:
    org_id, user_id = _ids(current_user)
    if bool(body.tool_id) == bool(body.action_id):
        raise HTTPException(status_code=400, detail="Pass exactly one of tool_id or action_id")
    try:
        uuid.UUID(body.action_id or body.tool_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid id")
    try:
        if body.action_id:
            await set_action_enabled(org_id, user_id, body.action_id, body.enabled)
        else:
            await set_tool_enabled(org_id, user_id, body.tool_id, body.enabled)
    except ComposioConnectorError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}
