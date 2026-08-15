"""
Workspace router — list the organizations the current user belongs to and switch
the active one.

Switching calls the keycloak-orgs `switch-organization` endpoint, which returns
a fresh token set (no re-login). The response hands those new tokens back to the
client, which stores them and refetches; every org-scoped route then resolves the
new active org through `get_current_context`.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Dict, List

from orgs.dependencies import get_current_context
from orgs.keycloak_orgs import get_orgs_client, KeycloakOrgsError
from orgs.models import WorkspaceOrganization, SwitchOrganizationRequest
from app.logger import logger

router = APIRouter(prefix="/workspace", tags=["workspace"])
security = HTTPBearer()


@router.get("/organizations", response_model=List[WorkspaceOrganization])
async def get_user_organizations(context: Dict = Depends(get_current_context)):
    """All organizations the current user is a member of."""
    client = get_orgs_client()
    current_org_id = context.get("organization_id")
    try:
        orgs = await client.list_user_orgs(context["id"])
    except KeycloakOrgsError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not list organizations: {e.message}",
        )

    result: List[WorkspaceOrganization] = []
    for o in orgs:
        oid = o.get("id")
        result.append(
            WorkspaceOrganization(
                id=oid,
                name=o.get("displayName") or o.get("name") or "Organization",
                # Role is known from the token for the active org; other orgs
                # default to "user" in the switcher (exact role is resolved once
                # you switch into them).
                role=context.get("role", "user") if oid == current_org_id else "user",
                status="active",
                is_current=(oid == current_org_id),
            )
        )
    return result


@router.post("/switch")
async def switch_organization(
    payload: SwitchOrganizationRequest,
    context: Dict = Depends(get_current_context),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Switch the active organization; returns a fresh token set (no re-login)."""
    client = get_orgs_client()
    try:
        tokens = await client.switch_active_org(credentials.credentials, payload.organization_id)
    except KeycloakOrgsError as e:
        if e.status_code in (401, 403):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not a member of this organization",
            )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Switch failed: {e.message}",
        )

    logger.info(f"[workspace] {context['id']} switched to org {payload.organization_id}")
    return {
        "message": "Organization switched successfully",
        "organization_id": payload.organization_id,
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type", "bearer"),
        "expires_in": tokens.get("expires_in"),
    }
