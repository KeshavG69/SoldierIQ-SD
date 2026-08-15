"""
Organization membership router (keycloak-orgs backed).

- List members: any active member of the org can see who's in it.
- Remove a member / change a member's role: **admin only**.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Dict, List

from orgs.dependencies import get_current_context, require_org_admin
from orgs.keycloak_orgs import get_orgs_client, KeycloakOrgsError, ADMIN_ROLE_SIGNAL
from app.logger import logger

router = APIRouter(prefix="/organizations", tags=["organizations"])


class RoleChange(BaseModel):
    role: str  # "admin" | "user"


@router.get("/me")
async def get_my_organization(context: dict = Depends(get_current_context)):
    """The caller's active organization."""
    return {
        "id": context.get("organization_id"),
        "name": context.get("organization_name"),
        "role": context.get("role"),
    }


@router.get("/me/members")
async def list_members(context: dict = Depends(get_current_context)):
    """List members of the active org, each with their role."""
    orgs = get_orgs_client()
    org_id = context["organization_id"]
    try:
        members = await orgs.list_members(org_id)
    except KeycloakOrgsError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not list members: {e.message}")

    result: List[dict] = []
    for m in members:
        uid = m.get("id")
        username = m.get("username") or ""
        email = m.get("email") or ""
        # keycloak-orgs auto-creates a synthetic per-org admin user
        # (org-admin-<uuid>@noreply…). It's not a real person — hide it.
        if username.startswith("org-admin-") or email.startswith("org-admin-"):
            continue
        role = "user"
        try:
            names = [r.get("name") for r in await orgs.get_user_org_roles(uid, org_id)]
            role = "admin" if ADMIN_ROLE_SIGNAL in names else "user"
        except KeycloakOrgsError:
            pass
        result.append({
            "user_id": uid,
            "username": m.get("username"),
            "email": m.get("email"),
            "firstName": m.get("firstName"),
            "lastName": m.get("lastName"),
            "role": role,
            "is_self": uid == context["id"],
        })
    return result


@router.delete("/members/{user_id}")
async def remove_member(user_id: str, context: dict = Depends(require_org_admin)):
    if user_id == context["id"]:
        raise HTTPException(status_code=400, detail="You cannot remove yourself from the organization")
    orgs = get_orgs_client()
    try:
        await orgs.remove_member(context["organization_id"], user_id)
    except KeycloakOrgsError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not remove member: {e.message}")
    return {"message": "Member removed", "user_id": user_id}


@router.post("/members/{user_id}/role")
async def change_member_role(user_id: str, payload: RoleChange, context: dict = Depends(require_org_admin)):
    if payload.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="role must be 'admin' or 'user'")
    if user_id == context["id"]:
        raise HTTPException(status_code=400, detail="You cannot change your own role")
    orgs = get_orgs_client()
    org_id = context["organization_id"]
    try:
        if payload.role == "admin":
            await orgs.make_admin(org_id, user_id)
        else:
            await orgs.make_member(org_id, user_id)
    except KeycloakOrgsError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not update role: {e.message}")
    return {"message": "Role updated", "user_id": user_id, "role": payload.role}
