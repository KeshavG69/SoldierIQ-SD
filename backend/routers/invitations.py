"""
Invitations router (keycloak-orgs backed).

- Send is **Admin or System Owner** (a System Owner may only invite plain
  Users; only an Admin can invite another Admin or System Owner).
- List / revoke are **admin-only**.
- Validate / accept are **public** — they power our own `/invite/accept` page.
  A new invitee is provisioned in Keycloak and auto-logged-in; an existing user
  is simply added to the organization.

Invitations are recorded in Keycloak (send=false → no Keycloak email); the admin
shares the returned accept link. The invitation id (an unguessable UUID) + org id
in the link are the capability to accept for that email.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any

from orgs.dependencies import require_org_admin, get_current_context
from orgs.keycloak_orgs import get_orgs_client, KeycloakOrgsError, ADMIN_ORG_ROLES, ADMIN_ROLE_SIGNAL, SYSTEM_OWNER_ROLE
from auth.keycloak_auth import get_keycloak_client
from clients.email_service import send_invitation_email
from app.settings import settings
from app.logger import logger

router = APIRouter(prefix="/invitations", tags=["invitations"])


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = Field("user", description="Role in the org: 'admin', 'system_owner', or 'user'")


class AcceptRequest(BaseModel):
    invitation_id: str
    organization_id: str
    firstName: Optional[str] = Field(None, min_length=1, max_length=100)
    lastName: Optional[str] = Field(None, min_length=1, max_length=100)
    password: Optional[str] = Field(None, min_length=8, max_length=128)


def _accept_link(inv_id: str, org_id: str) -> str:
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/invite/accept?inv={inv_id}&org={org_id}"


def _role_of(roles: List[str]) -> str:
    roles = roles or []
    if ADMIN_ROLE_SIGNAL in roles:
        return "admin"
    if SYSTEM_OWNER_ROLE in roles:
        return "system_owner"
    return "user"


async def _find_invitation(orgs, org_id: str, invitation_id: str) -> Optional[dict]:
    invites = await orgs.list_invitations(org_id)
    return next((i for i in invites if i.get("id") == invitation_id), None)


async def require_admin_or_system_owner(context: dict = Depends(get_current_context)) -> dict:
    """Admin or System Owner — both may send invitations (System Owner is
    further restricted to inviting plain Users, checked in the handler)."""
    if context.get("role") not in ("admin", "system_owner"):
        raise HTTPException(status_code=403, detail="Admin or System Owner privileges required")
    return context


# --------------------------------------------------------- admin / system owner
@router.post("")
async def send_invitation(payload: InviteRequest, context: dict = Depends(require_admin_or_system_owner)):
    if payload.role not in ("admin", "system_owner", "user"):
        raise HTTPException(status_code=400, detail="role must be 'admin', 'system_owner', or 'user'")
    # System Owners may only onboard plain Users; only an Admin can create
    # another Admin or System Owner.
    if context.get("role") == "system_owner" and payload.role != "user":
        raise HTTPException(status_code=403, detail="System Owners can only invite Users")
    orgs = get_orgs_client()
    org_id = context["organization_id"]
    if payload.role == "admin":
        roles = ADMIN_ORG_ROLES
    elif payload.role == "system_owner":
        await orgs.ensure_org_role(
            org_id, SYSTEM_OWNER_ROLE, "Can upload documents and see all organization documents"
        )
        roles = [SYSTEM_OWNER_ROLE]
    else:
        roles = []
    try:
        inv_id = await orgs.create_invitation(
            org_id=org_id, email=payload.email, inviter_id=context["id"],
            roles=roles, send=False,
        )
    except KeycloakOrgsError as e:
        if e.status_code == 409:
            raise HTTPException(status_code=400, detail="An invitation for this email already exists")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not create invitation: {e.message}")
    accept_url = _accept_link(inv_id, org_id)
    org_name = context.get("organization_name") or "your organization"
    inviter = (
        " ".join(filter(None, [context.get("firstName"), context.get("lastName")]))
        or context.get("username")
        or "A teammate"
    )
    emailed = await send_invitation_email(
        to_email=payload.email,
        accept_url=accept_url,
        organization_name=org_name,
        role=payload.role,
        invited_by=inviter,
    )
    return {
        "message": "Invitation sent" if emailed else "Invitation created",
        "invitation_id": inv_id,
        "email": payload.email,
        "role": payload.role,
        "accept_url": accept_url,
        "emailed": emailed,
    }


@router.get("")
async def list_org_invitations(context: dict = Depends(require_org_admin)):
    orgs = get_orgs_client()
    try:
        invites = await orgs.list_invitations(context["organization_id"])
    except KeycloakOrgsError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not list invitations: {e.message}")
    return [
        {
            "id": i.get("id"),
            "email": i.get("email"),
            "role": _role_of(i.get("roles")),
            "createdAt": i.get("createdAt") or i.get("created_at"),
        }
        for i in invites
    ]


@router.delete("/{invitation_id}")
async def revoke_invitation(invitation_id: str, context: dict = Depends(require_org_admin)):
    orgs = get_orgs_client()
    try:
        await orgs.delete_invitation(context["organization_id"], invitation_id)
    except KeycloakOrgsError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not revoke invitation: {e.message}")
    return {"message": "Invitation revoked", "invitation_id": invitation_id}


# -------------------------------------------------------------------- public
@router.get("/validate")
async def validate_invitation(inv: str, org: str):
    """Public: describe an invitation so the accept page can render it."""
    orgs = get_orgs_client()
    try:
        invite = await _find_invitation(orgs, org, inv)
    except KeycloakOrgsError:
        invite = None
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")

    org_doc: Dict[str, Any] = {}
    try:
        org_doc = await orgs.get_org(org)
    except KeycloakOrgsError:
        pass
    existing = None
    try:
        existing = await orgs.find_user(email=invite.get("email"))
    except KeycloakOrgsError:
        pass

    return {
        "email": invite.get("email"),
        "organization_name": org_doc.get("displayName") or org_doc.get("name"),
        "role": _role_of(invite.get("roles")),
        "user_exists": existing is not None,
    }


@router.post("/accept")
async def accept_invitation(payload: AcceptRequest):
    """Public: join the organization the invitation is for."""
    orgs = get_orgs_client()
    invite = await _find_invitation(orgs, payload.organization_id, payload.invitation_id)
    if not invite:
        raise HTTPException(status_code=404, detail="Invitation not found or already used")

    email = invite.get("email")
    roles = invite.get("roles") or []
    existing = await orgs.find_user(email=email)

    if existing:
        user_id = existing["id"]
    else:
        if not (payload.firstName and payload.lastName and payload.password):
            raise HTTPException(
                status_code=400,
                detail="firstName, lastName and password are required to create your account",
            )
        user_id = await orgs.create_user(
            username=email, email=email,
            first_name=payload.firstName, last_name=payload.lastName,
            password=payload.password,
        )

    # Add to the org and grant the invited roles.
    try:
        await orgs.add_member(payload.organization_id, user_id)
        for r in roles:
            try:
                await orgs.grant_org_role(payload.organization_id, r, user_id)
            except KeycloakOrgsError as e:
                logger.warning(f"[invite] grant {r} failed: {e}")
    except KeycloakOrgsError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not join organization: {e.message}")

    # Consume the invitation.
    try:
        await orgs.delete_invitation(payload.organization_id, payload.invitation_id)
    except KeycloakOrgsError:
        pass

    resp: Dict[str, Any] = {"message": "Invitation accepted", "organization_id": payload.organization_id}

    # Brand-new user: hand back tokens so the frontend can log them straight in.
    if not existing and payload.password:
        try:
            tokens = get_keycloak_client().token(username=email, password=payload.password)
            resp.update({
                "access_token": tokens.get("access_token"),
                "refresh_token": tokens.get("refresh_token"),
                "token_type": "bearer",
                "expires_in": tokens.get("expires_in"),
            })
        except Exception as e:
            logger.warning(f"[invite] auto-login after accept failed: {e}")

    return resp
