"""
Self-service access requests.

A person who wants **System Owner** access to an org submits a request naming
the org **admin's email** (no account needed — this is public, from the login
page). The targeted admin later sees the request in their Team panel and
approves it **per org**: approving in the active org sends the requester a
System Owner invitation for THAT org (reusing the invitation flow), and records
the org as granted. Because one admin email can be admin of several orgs, the
admin switches into each org and approves separately — a request stays pending
in every org where it hasn't been granted yet.

Requests live in Postgres (they aren't a Keycloak concept); the actual join is
still a Keycloak-orgs invitation.
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from orgs.dependencies import require_org_admin
from orgs.keycloak_orgs import get_orgs_client, KeycloakOrgsError, SYSTEM_OWNER_ROLE, ADMIN_ROLE_SIGNAL
from clients.postgres_client import get_postgres_client
from clients.email_service import send_invitation_email
from app.settings import settings
from app.logger import logger

router = APIRouter(prefix="/access-requests", tags=["access-requests"])


_TABLE_READY = False

_DDL = """
CREATE TABLE IF NOT EXISTS access_requests (
    id UUID PRIMARY KEY,
    requester_email TEXT NOT NULL,
    requester_name TEXT,
    admin_email TEXT NOT NULL,
    message TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    granted_org_ids TEXT[] NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_access_requests_admin_email
    ON access_requests (lower(admin_email));
"""


async def _ensure_table():
    """Create the table on first use (idempotent) so this feature needs no
    separate migration step."""
    global _TABLE_READY
    if _TABLE_READY:
        return
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        await c.execute(_DDL)
    _TABLE_READY = True


def _accept_link(inv_id: str, org_id: str) -> str:
    base = (settings.FRONTEND_URL or "").rstrip("/")
    return f"{base}/invite/accept?inv={inv_id}&org={org_id}"


# ------------------------------------------------------------------- public
class AccessRequestCreate(BaseModel):
    requester_email: EmailStr
    admin_email: EmailStr
    requester_name: Optional[str] = Field(None, max_length=200)
    message: Optional[str] = Field(None, max_length=1000)


@router.post("")
async def create_access_request(payload: AccessRequestCreate):
    """Public: submit a request for System Owner access, addressed to an
    org admin's email."""
    await _ensure_table()
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        await c.execute(
            """
            INSERT INTO access_requests (id, requester_email, requester_name, admin_email, message)
            VALUES ($1, $2, $3, $4, $5)
            """,
            uuid.uuid4(),
            str(payload.requester_email).strip().lower(),
            (payload.requester_name or "").strip() or None,
            str(payload.admin_email).strip().lower(),
            (payload.message or "").strip() or None,
        )
    logger.info(f"📨 Access request from {payload.requester_email} → admin {payload.admin_email}")
    return {"message": "Request submitted. An admin will review it shortly."}


# -------------------------------------------------------------- admin (per org)
@router.get("")
async def list_access_requests(context: dict = Depends(require_org_admin)):
    """Pending requests addressed to THIS admin that haven't been granted in
    the active org yet."""
    await _ensure_table()
    admin_email = (context.get("email") or "").strip().lower()
    org_id = context["organization_id"]
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        rows = await c.fetch(
            """
            SELECT id, requester_email, requester_name, message, created_at
            FROM access_requests
            WHERE lower(admin_email) = $1
              AND status = 'pending'
              AND NOT ($2 = ANY(granted_org_ids))
            ORDER BY created_at DESC
            """,
            admin_email,
            org_id,
        )
    return [
        {
            "id": str(r["id"]),
            "requester_email": r["requester_email"],
            "requester_name": r["requester_name"],
            "message": r["message"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]


async def _load_request_for_admin(c, request_id: str, admin_email: str):
    try:
        rid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request id")
    row = await c.fetchrow("SELECT * FROM access_requests WHERE id = $1", rid)
    if not row:
        raise HTTPException(status_code=404, detail="Request not found")
    # Only the admin the request is addressed to may act on it.
    if (row["admin_email"] or "").strip().lower() != admin_email:
        raise HTTPException(status_code=403, detail="This request is addressed to a different admin")
    return row


@router.post("/{request_id}/approve")
async def approve_access_request(request_id: str, context: dict = Depends(require_org_admin)):
    """Approve for the ACTIVE org: send the requester a System Owner invitation
    and mark this org granted. The request stays pending for the admin's other
    orgs so they can grant there too."""
    await _ensure_table()
    admin_email = (context.get("email") or "").strip().lower()
    org_id = context["organization_id"]
    org_name = context.get("organization_name") or "your organization"

    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        row = await _load_request_for_admin(c, request_id, admin_email)
        if row["status"] != "pending":
            raise HTTPException(status_code=400, detail="This request is no longer pending")
        if org_id in (row["granted_org_ids"] or []):
            raise HTTPException(status_code=400, detail="Already granted in this organization")

        orgs = get_orgs_client()
        requester_email = row["requester_email"]

        # Does this person already have an account? If so, we upgrade them
        # directly instead of inviting (inviting an existing member fails with
        # "invitation already exists"). If not, we send an invitation so they
        # can create an account and join.
        try:
            existing = await orgs.find_user(email=requester_email)
        except KeycloakOrgsError:
            existing = None

        direct_grant = False
        if existing:
            user_id = existing["id"]
            # Already an admin here? Don't downgrade them to System Owner.
            already_admin = False
            try:
                names = [r.get("name") for r in await orgs.get_user_org_roles(user_id, org_id)]
                already_admin = ADMIN_ROLE_SIGNAL in names
            except KeycloakOrgsError:
                names = []
            if already_admin:
                raise HTTPException(
                    status_code=400,
                    detail="This person is already an admin of this organization",
                )
            # Ensure they're a member of this org, then grant System Owner.
            try:
                await orgs.add_member(org_id, user_id)  # no-op if already a member
            except KeycloakOrgsError:
                pass
            try:
                await orgs.make_system_owner(org_id, user_id)
            except KeycloakOrgsError as e:
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not grant access: {e.message}")
            direct_grant = True
            inv_id = None
        else:
            # New person → System Owner invitation.
            try:
                await orgs.ensure_org_role(
                    org_id, SYSTEM_OWNER_ROLE, "Can upload documents and see all organization documents"
                )
                inv_id = await orgs.create_invitation(
                    org_id=org_id,
                    email=requester_email,
                    inviter_id=context["id"],
                    roles=[SYSTEM_OWNER_ROLE],
                    send=False,
                )
            except KeycloakOrgsError as e:
                if e.status_code == 409:
                    raise HTTPException(status_code=400, detail="An invitation for this email already exists in this org")
                raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not create invitation: {e.message}")

        # Record this org as granted.
        await c.execute(
            "UPDATE access_requests SET granted_org_ids = array_append(granted_org_ids, $1), updated_at = now() WHERE id = $2",
            org_id,
            row["id"],
        )

    # Existing member upgraded in place — no email needed.
    if direct_grant:
        return {
            "message": "Request approved — granted System Owner access",
            "requester_email": requester_email,
            "accept_url": None,
            "emailed": False,
        }

    accept_url = _accept_link(inv_id, org_id)
    inviter = (
        " ".join(filter(None, [context.get("firstName"), context.get("lastName")]))
        or context.get("username")
        or "An administrator"
    )
    emailed = await send_invitation_email(
        to_email=requester_email,
        accept_url=accept_url,
        organization_name=org_name,
        role="system_owner",
        invited_by=inviter,
    )
    return {
        "message": "Request approved — invitation sent" if emailed else "Request approved — invitation created",
        "requester_email": requester_email,
        "accept_url": accept_url,
        "emailed": emailed,
    }


@router.post("/{request_id}/deny")
async def deny_access_request(request_id: str, context: dict = Depends(require_org_admin)):
    """Deny the request entirely (removes it from every org's pending list)."""
    await _ensure_table()
    admin_email = (context.get("email") or "").strip().lower()
    pool = await get_postgres_client().get_pool()
    async with pool.acquire() as c:
        row = await _load_request_for_admin(c, request_id, admin_email)
        await c.execute(
            "UPDATE access_requests SET status = 'denied', updated_at = now() WHERE id = $1",
            row["id"],
        )
    return {"message": "Request denied", "id": request_id}
