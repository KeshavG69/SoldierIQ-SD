"""
Keycloak Authentication Integration
Handles JWT token validation and user authentication via Keycloak
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from keycloak import KeycloakOpenID, KeycloakAdmin, KeycloakOpenIDConnection
from typing import Dict
from functools import lru_cache
import json
import base64
import re
from jose import jwt as jose_jwt, JWTError

from app.settings import settings
from app.logger import logger


# HTTP Bearer security scheme for extracting tokens from Authorization header
security = HTTPBearer()


def _decode_jwt_payload(token: str) -> Dict:
    """Base64-decode a JWT's payload (no signature check). Used only to read a
    claim from a token that has ALREADY been validated via introspection."""
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def _parse_active_org(raw) -> Dict:
    """Normalize the `active_organization` claim to {id, name, role[]}.

    The keycloak-orgs mapper serializes it as a Java-map string like
    `{role=[manage-organization], name=Acme, id=<uuid>, attribute={}}` rather
    than JSON, so parse that form defensively (id + role are load-bearing; name
    is display-only)."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        v = json.loads(raw)
        if isinstance(v, dict):
            return v
    except Exception:
        pass
    out: Dict = {}
    m = re.search(r"\bid=([0-9a-fA-F-]{36})", raw)
    if m:
        out["id"] = m.group(1)
    m = re.search(r"\brole=\[([^\]]*)\]", raw)
    if m:
        out["role"] = [r.strip() for r in m.group(1).split(",") if r.strip()]
    m = re.search(r"\bname=(.+?),\s+(?:id|role|attribute)=", raw)
    if m:
        out["name"] = m.group(1).strip()
    return out


@lru_cache()
def _realm_public_key() -> str:
    """Realm RSA public key as PEM, for local RS256 token verification. Cached;
    a server restart re-fetches it if Keycloak ever rotates its signing key."""
    key = get_keycloak_client().public_key()
    return f"-----BEGIN PUBLIC KEY-----\n{key}\n-----END PUBLIC KEY-----"


@lru_cache()
def get_keycloak_client() -> KeycloakOpenID:
    """
    Get or create Keycloak OpenID Connect client (singleton pattern)

    This function is cached, so the Keycloak client is only created once
    and reused across all requests for better performance.

    Returns:
        KeycloakOpenID: Configured Keycloak client
    """
    try:
        keycloak_openid = KeycloakOpenID(
            # python-keycloak joins paths with urljoin, which drops a base-path
            # segment when there's no trailing slash (".../auth" -> 404). Force "/".
            server_url=settings.KEYCLOAK_SERVER_URL.rstrip("/") + "/",
            client_id=settings.KEYCLOAK_CLIENT_ID,
            realm_name=settings.KEYCLOAK_REALM,
            client_secret_key=settings.KEYCLOAK_CLIENT_SECRET,
            verify=True  # Verify SSL certificates in production
        )

        logger.info(f"✅ Keycloak client initialized for realm: {settings.KEYCLOAK_REALM}")
        return keycloak_openid

    except Exception as e:
        logger.error(f"❌ Failed to initialize Keycloak client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service unavailable"
        )


@lru_cache()
def get_keycloak_admin() -> KeycloakAdmin:
    """
    Get or create Keycloak Admin client (singleton pattern)

    Admin authenticates against 'master' realm but manages users in target realm.

    Returns:
        KeycloakAdmin: Configured Keycloak admin client
    """
    try:
        # Create connection - admin user is in master realm
        keycloak_connection = KeycloakOpenIDConnection(
            server_url=settings.KEYCLOAK_SERVER_URL.rstrip("/") + "/",
            username=settings.KEYCLOAK_ADMIN_USERNAME,
            password=settings.KEYCLOAK_ADMIN_PASSWORD,
            realm_name="master",
            client_id="admin-cli",
            verify=True
        )

        # Create admin client
        keycloak_admin = KeycloakAdmin(connection=keycloak_connection)

        # Important! Call get_realm() on master first (initializes connection properly)
        keycloak_admin.get_realm("master")

        # Now switch to target realm for user management
        keycloak_admin.change_current_realm(settings.KEYCLOAK_REALM)

        logger.info(f"✅ Keycloak admin client initialized for realm: {settings.KEYCLOAK_REALM}")
        return keycloak_admin

    except Exception as e:
        logger.error(f"❌ Failed to initialize Keycloak admin client: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User management service unavailable"
        )


async def get_current_user_keycloak(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> Dict:
    """
    Validate JWT token with Keycloak and return user information

    This is a FastAPI dependency that:
    1. Extracts the Bearer token from Authorization header
    2. Validates the token with Keycloak
    3. Returns user information if token is valid
    4. Raises 401 error if token is invalid/expired

    Args:
        credentials: HTTP Bearer token from Authorization header

    Returns:
        Dict with user information:
        {
            "id": "user-uuid",
            "email": "user@example.com",
            "username": "testuser",
            "firstName": "Test",
            "lastName": "User",
            "email_verified": True
        }

    Raises:
        HTTPException 401: If token is invalid, expired, or user not found
    """
    token = credentials.credentials

    try:
        # Validate the token locally against the realm's RS256 public key. Faster
        # than introspection (no per-request network call) and, unlike this
        # Keycloak's introspection endpoint, it exposes the full claim set —
        # including the keycloak-orgs `active_organization` mapper claim.
        claims = jose_jwt.decode(
            token,
            _realm_public_key(),
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired",
        )

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing subject",
        )

    active_org = _parse_active_org(claims.get("active_organization"))

    user_data = {
        "id": user_id,
        "username": claims.get("preferred_username"),
        "email": claims.get("email"),
        "firstName": claims.get("given_name"),
        "lastName": claims.get("family_name"),
        "email_verified": claims.get("email_verified", False),
        "realm_roles": claims.get("realm_access", {}).get("roles", []),
        "organization_id": claims.get("organization_id"),
        "organization_name": claims.get("organization_name"),
        "active_organization": active_org,
    }
    return user_data


async def get_current_user_id_keycloak(
    current_user: Dict = Depends(get_current_user_keycloak)
) -> str:
    """
    Get current user's ID from Keycloak

    Convenience dependency for endpoints that only need the user ID.

    Args:
        current_user: User dict from get_current_user_keycloak dependency

    Returns:
        User's ID as string
    """
    return current_user["id"]


def verify_user_role(required_role: str):
    """
    Decorator to check if user has a specific role

    Usage:
        @router.get("/admin")
        async def admin_endpoint(user = Depends(verify_user_role("admin"))):
            return {"message": "Admin access granted"}

    Args:
        required_role: Role name required to access the endpoint

    Returns:
        Dependency function that validates role
    """
    async def role_checker(current_user: Dict = Depends(get_current_user_keycloak)) -> Dict:
        user_roles = current_user.get("realm_roles", [])

        if required_role not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User does not have required role: {required_role}"
            )

        return current_user

    return role_checker
