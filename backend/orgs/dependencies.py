"""
Organization-aware request context, backed by Keycloak + the keycloak-orgs
extension.

`get_current_context` takes the Keycloak identity (`get_current_user_keycloak`)
and derives the **active organization** and the user's **role** in it from the
`active_organization` token claim (added by the extension's mapper). It returns
the same dict shape existing routes consume — `current_user["organization_id"]`
and `current_user["role"]` — so a route becomes org-aware just by swapping:

    Depends(get_current_user_keycloak)  ->  Depends(get_current_context)
"""

from fastapi import Depends, HTTPException, status
from typing import Dict, List, Any

from auth.keycloak_auth import get_current_user_keycloak
from orgs.keycloak_orgs import get_orgs_client, ADMIN_ROLE_SIGNAL, SYSTEM_OWNER_ROLE
from app.logger import logger


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def _resolve_role(org_roles: List[str]) -> str:
    """admin (manage-organization) > system_owner (custom role) > user."""
    if ADMIN_ROLE_SIGNAL in org_roles:
        return "admin"
    if SYSTEM_OWNER_ROLE in org_roles:
        return "system_owner"
    return "user"


async def get_current_context(
    current_user: Dict = Depends(get_current_user_keycloak),
) -> Dict:
    """Identity (Keycloak) + active organization (keycloak-orgs).

    Sets on the returned dict:
    - organization_id   : active org id (namespaces the FalkorDB graph)
    - organization_name : active org display name
    - role              : "admin" | "system_owner" | "user"
    - org_roles         : raw org-role names for the active org
    """
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject",
        )

    active = current_user.get("active_organization") or {}
    org_id = active.get("id")
    org_name = active.get("name")
    org_roles = _as_list(active.get("role") or active.get("roles"))

    # Fallback: the token has no active-org claim yet (e.g. a token minted before
    # the extension auto-assigned a first org). Resolve it over REST.
    if not org_id:
        try:
            orgs = await get_orgs_client().list_user_orgs(user_id)
        except Exception as e:
            logger.warning(f"[orgs] list_user_orgs fallback failed for {user_id}: {e}")
            orgs = []
        if not orgs:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not belong to any organization yet",
            )
        org_id = orgs[0].get("id")
        org_name = orgs[0].get("displayName") or orgs[0].get("name")
        try:
            roles = await get_orgs_client().get_user_org_roles(user_id, org_id)
            org_roles = [r.get("name") for r in roles if isinstance(r, dict) and r.get("name")]
        except Exception:
            org_roles = []

    current_user["organization_id"] = org_id
    current_user["organization_name"] = org_name
    current_user["role"] = _resolve_role(org_roles)
    current_user["org_roles"] = org_roles
    return current_user


async def require_org_admin(context: Dict = Depends(get_current_context)) -> Dict:
    """Require the caller to be an admin of their active organization."""
    if context.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this organization",
        )
    return context


async def require_uploader(context: Dict = Depends(get_current_context)) -> Dict:
    """Require the caller to be an Admin or System Owner (can ingest documents).
    Plain Users are read-only: they can view/query but not upload or manage
    documents/folders."""
    if context.get("role") not in ("admin", "system_owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or System Owner privileges required to upload documents",
        )
    return context
