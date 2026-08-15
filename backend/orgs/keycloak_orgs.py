"""
Client for the Phase Two `keycloak-orgs` REST API.

Keycloak is the source of truth for organizations, memberships, per-org roles,
and invitations. This module wraps the extension's REST endpoints (exact paths
from the Phase Two OpenAPI spec) so the rest of the backend never speaks HTTP
to Keycloak directly.

Auth model:
- **Admin/management calls** (create org, add member, grant role, invitations…)
  use a **service-account token** — a client-credentials token for the
  confidential `soldieriq-backend` client, which holds the `realm-management`
  + org-management roles.
- **User-context calls** (`switch-organization`, `active-organization`) act on
  the calling user, so they forward that **user's own bearer token** instead.

All paths are relative to `{KEYCLOAK_SERVER_URL}/realms/{realm}`.
"""

import time
import httpx
from typing import Optional, List, Dict, Any

from app.settings import settings
from app.logger import logger


# Built-in keycloak-orgs role names. Granting the manage-* set is how we mark a
# member as an "admin" of an org; a plain member (no manage-* roles) is a "user".
# `manage-organization` is the signal the backend checks in the token claim.
ADMIN_ORG_ROLES = [
    "view-organization",
    "manage-organization",
    "view-members",
    "manage-members",
    "view-roles",
    "manage-roles",
    "view-invitations",
    "manage-invitations",
]
ADMIN_ROLE_SIGNAL = "manage-organization"


class KeycloakOrgsError(Exception):
    """Raised when the keycloak-orgs API returns an error status."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")


class KeycloakOrgsClient:
    def __init__(self):
        base = settings.KEYCLOAK_SERVER_URL.rstrip("/")
        self._realm_base = f"{base}/realms/{settings.KEYCLOAK_REALM}"
        self._token_url = f"{self._realm_base}/protocol/openid-connect/token"
        self._client_id = settings.KEYCLOAK_CLIENT_ID
        self._client_secret = settings.KEYCLOAK_CLIENT_SECRET
        self._sa_token: Optional[str] = None
        self._sa_exp: float = 0.0

    # ------------------------------------------------------------------ auth
    async def _service_token(self) -> str:
        """Cached client-credentials token for the backend service account."""
        now = time.time()
        if self._sa_token and now < self._sa_exp - 30:
            return self._sa_token
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(
                self._token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
        if resp.status_code != 200:
            raise KeycloakOrgsError(resp.status_code, f"service token failed: {resp.text}")
        data = resp.json()
        self._sa_token = data["access_token"]
        self._sa_exp = now + int(data.get("expires_in", 60))
        return self._sa_token

    async def _admin(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        token = await self._service_token()
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.request(
                method,
                f"{self._realm_base}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
            )
        if resp.status_code >= 400:
            raise KeycloakOrgsError(
                resp.status_code, f"{method} {path} -> {resp.status_code}: {resp.text}"
            )
        return resp

    @staticmethod
    def _id_from_location(resp: httpx.Response) -> Optional[str]:
        loc = resp.headers.get("Location") or resp.headers.get("location")
        if loc:
            return loc.rstrip("/").split("/")[-1]
        try:
            body = resp.json()
            if isinstance(body, dict):
                return body.get("id")
        except Exception:
            pass
        return None

    # ------------------------------------------------ users (Keycloak Admin API)
    async def _kc_admin(
        self, method: str, path: str, *, json: Any = None, params: Optional[dict] = None
    ) -> httpx.Response:
        """Call the standard Keycloak Admin REST API (`/admin/realms/{realm}...`)
        with the service-account token — used to provision users."""
        token = await self._service_token()
        base = f"{settings.KEYCLOAK_SERVER_URL.rstrip('/')}/admin/realms/{settings.KEYCLOAK_REALM}"
        async with httpx.AsyncClient(timeout=20) as c:
            resp = await c.request(
                method, f"{base}{path}",
                headers={"Authorization": f"Bearer {token}"}, json=json, params=params,
            )
        if resp.status_code >= 400:
            raise KeycloakOrgsError(resp.status_code, f"{method} {path} -> {resp.status_code}: {resp.text}")
        return resp

    async def find_user(self, username: Optional[str] = None, email: Optional[str] = None) -> Optional[dict]:
        params: Dict[str, Any] = {"exact": "true", "max": 1}
        if username:
            params["username"] = username
        if email:
            params["email"] = email
        users = (await self._kc_admin("GET", "/users", params=params)).json()
        return users[0] if users else None

    async def create_user(
        self, username: str, email: str, first_name: str, last_name: str, password: str,
        email_verified: bool = True, enabled: bool = True,
    ) -> str:
        """Create a Keycloak user with a password; returns the new user id."""
        body = {
            "username": username, "email": email,
            "firstName": first_name, "lastName": last_name,
            "enabled": enabled, "emailVerified": email_verified,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        resp = await self._kc_admin("POST", "/users", json=body)
        uid = self._id_from_location(resp)
        if not uid:
            found = await self.find_user(username=username)
            uid = found.get("id") if found else None
        if not uid:
            raise KeycloakOrgsError(500, "user created but no id returned")
        return uid

    # ---------------------------------------------------------- organizations
    async def create_org(
        self, name: str, display_name: Optional[str] = None, attributes: Optional[dict] = None
    ) -> str:
        """Create an organization; returns the new org id."""
        body: Dict[str, Any] = {"name": name, "displayName": display_name or name}
        if attributes:
            body["attributes"] = attributes
        resp = await self._admin("POST", "/orgs", json=body)
        org_id = self._id_from_location(resp)
        if not org_id:
            raise KeycloakOrgsError(500, "org created but no id returned")
        return org_id

    async def get_org(self, org_id: str) -> dict:
        return (await self._admin("GET", f"/orgs/{org_id}")).json()

    async def list_user_orgs(self, user_id: str) -> List[dict]:
        """Organizations a user belongs to (id, name, displayName, …)."""
        return (await self._admin("GET", f"/users/{user_id}/orgs")).json()

    # -------------------------------------------------------------- members
    async def add_member(self, org_id: str, user_id: str) -> None:
        await self._admin("PUT", f"/orgs/{org_id}/members/{user_id}")

    async def remove_member(self, org_id: str, user_id: str) -> None:
        await self._admin("DELETE", f"/orgs/{org_id}/members/{user_id}")

    async def list_members(self, org_id: str) -> List[dict]:
        return (await self._admin("GET", f"/orgs/{org_id}/members")).json()

    # ---------------------------------------------------------------- roles
    async def list_org_roles(self, org_id: str) -> List[dict]:
        return (await self._admin("GET", f"/orgs/{org_id}/roles")).json()

    async def grant_org_role(self, org_id: str, role_name: str, user_id: str) -> None:
        await self._admin("PUT", f"/orgs/{org_id}/roles/{role_name}/users/{user_id}")

    async def revoke_org_role(self, org_id: str, role_name: str, user_id: str) -> None:
        await self._admin("DELETE", f"/orgs/{org_id}/roles/{role_name}/users/{user_id}")

    async def get_user_org_roles(self, user_id: str, org_id: str) -> List[dict]:
        return (await self._admin("GET", f"/users/{user_id}/orgs/{org_id}/roles")).json()

    async def make_admin(self, org_id: str, user_id: str) -> None:
        """Grant the full manage-* role set (best-effort per role)."""
        for role in ADMIN_ORG_ROLES:
            try:
                await self.grant_org_role(org_id, role, user_id)
            except KeycloakOrgsError as e:
                # Some role names can vary by version; don't fail the whole op.
                logger.warning(f"[orgs] grant {role} on {org_id} -> {e.status_code}")

    async def make_member(self, org_id: str, user_id: str) -> None:
        """Demote to plain member: revoke the manage-* roles (keeps view-*)."""
        for role in [r for r in ADMIN_ORG_ROLES if r.startswith("manage-")]:
            try:
                await self.revoke_org_role(org_id, role, user_id)
            except KeycloakOrgsError as e:
                logger.warning(f"[orgs] revoke {role} on {org_id} -> {e.status_code}")

    # ---------------------------------------------------------- invitations
    async def create_invitation(
        self,
        org_id: str,
        email: str,
        inviter_id: str,
        roles: Optional[List[str]] = None,
        redirect_uri: Optional[str] = None,
        send: bool = True,
    ) -> Optional[str]:
        body: Dict[str, Any] = {"email": email, "inviterId": inviter_id, "send": send}
        if roles:
            body["roles"] = roles
        if redirect_uri:
            body["redirectUri"] = redirect_uri
        resp = await self._admin("POST", f"/orgs/{org_id}/invitations", json=body)
        return self._id_from_location(resp)

    async def list_invitations(self, org_id: str) -> List[dict]:
        return (await self._admin("GET", f"/orgs/{org_id}/invitations")).json()

    async def delete_invitation(self, org_id: str, invitation_id: str) -> None:
        await self._admin("DELETE", f"/orgs/{org_id}/invitations/{invitation_id}")

    # -------------------------------------------------- user-context (switch)
    async def switch_active_org(self, user_token: str, org_id: str) -> dict:
        """Switch the calling user's active org. Returns a NEW token set
        (access_token, refresh_token, …) — no re-login needed."""
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.request(
                "PUT",
                f"{self._realm_base}/users/switch-organization",
                headers={"Authorization": f"Bearer {user_token}"},
                json={"id": org_id},
            )
        if resp.status_code >= 400:
            raise KeycloakOrgsError(
                resp.status_code, f"switch-organization -> {resp.status_code}: {resp.text}"
            )
        return resp.json()

    async def get_active_org(self, user_token: str) -> dict:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get(
                f"{self._realm_base}/users/active-organization",
                headers={"Authorization": f"Bearer {user_token}"},
            )
        if resp.status_code >= 400:
            raise KeycloakOrgsError(
                resp.status_code, f"active-organization -> {resp.status_code}: {resp.text}"
            )
        return resp.json()


# ---------------------------------------------------------------------------
_orgs_client: Optional[KeycloakOrgsClient] = None


def get_orgs_client() -> KeycloakOrgsClient:
    global _orgs_client
    if _orgs_client is None:
        _orgs_client = KeycloakOrgsClient()
    return _orgs_client
