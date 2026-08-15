"""
Per-document access control (RBAC by email).

An org **admin** grants/revokes which members may see each document. Backed by
the graph's `HAS_ACCESS` edges (`clients/kg/rbac.RBACManager`). Enforcement:
- the document list hides documents a member hasn't been granted,
- retrieval scopes a member's search to their granted documents,
- admins (who manage the org) see and query everything.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from typing import Dict, List

from orgs.dependencies import require_org_admin
from clients.kg.rbac import RBACManager
from app.logger import logger

router = APIRouter(prefix="/documents", tags=["document-access"])


class GrantAccessRequest(BaseModel):
    email: EmailStr


@router.get("/{document_id}/access")
async def get_document_access(document_id: str, context: dict = Depends(require_org_admin)):
    """List the emails that can access a document (admin only)."""
    try:
        emails = await RBACManager(context["organization_id"]).who_can_access(document_id)
    except Exception as e:
        logger.error(f"[doc-access] who_can_access failed: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not read document access")
    return {"document_id": document_id, "emails": sorted({e for e in emails if e})}


@router.post("/{document_id}/access")
async def grant_document_access(
    document_id: str, payload: GrantAccessRequest, context: dict = Depends(require_org_admin)
):
    """Grant a member access to a document (admin only)."""
    granter = context.get("email") or context.get("username") or ""
    try:
        await RBACManager(context["organization_id"]).grant_access(
            email=payload.email, document_id=document_id, granted_by=granter
        )
    except Exception as e:
        logger.error(f"[doc-access] grant failed: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not grant access")
    return {"message": "Access granted", "document_id": document_id, "email": payload.email}


@router.delete("/{document_id}/access")
async def revoke_document_access(
    document_id: str, email: str, context: dict = Depends(require_org_admin)
):
    """Revoke a member's access to a document (admin only). `email` is a query param."""
    try:
        await RBACManager(context["organization_id"]).revoke_access(email=email, document_id=document_id)
    except Exception as e:
        logger.error(f"[doc-access] revoke failed: {e}")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not revoke access")
    return {"message": "Access revoked", "document_id": document_id, "email": email}
