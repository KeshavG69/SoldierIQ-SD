"""
Authentication router for user management endpoints.
All authentication handled via Keycloak.
"""

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
import uuid

# Keycloak Authentication imports
from auth.keycloak_auth import get_current_user_keycloak, get_keycloak_client, get_keycloak_admin
from orgs.keycloak_orgs import get_orgs_client, KeycloakOrgsError, SYSTEM_OWNER_ROLE
from orgs.dependencies import get_current_context
from app.logger import logger

router = APIRouter(prefix="/auth", tags=["authentication"])


# ==================== REQUEST/RESPONSE MODELS ====================

class SignupRequest(BaseModel):
    """User registration request"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(..., min_length=8)
    firstName: str
    lastName: str


class SignupResponse(BaseModel):
    """User registration response"""
    id: str
    username: str
    email: str
    firstName: str
    lastName: str
    organization_id: str
    organization_name: str
    message: str


class LoginRequest(BaseModel):
    """User login request"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """User login response with tokens"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """Refresh token request"""
    refresh_token: str


class UserInfoResponse(BaseModel):
    """Current user information response"""
    id: str
    username: str
    email: str
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    email_verified: bool
    roles: list[str] = []
    organization_id: Optional[str] = None
    organization_name: Optional[str] = None
    role: Optional[str] = None  # role in the active org: "admin" | "system_owner" | "user"


# ==================== ENDPOINTS ====================

@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(user_data: SignupRequest):
    """
    Register a new user and create their personal organization.

    All operations run through the keycloak-orgs service account (no
    master-admin credentials):
    1. Reject if the username/email already exists.
    2. Create the Keycloak user.
    3. Create their personal organization.
    4. Add them as a member and grant admin (manage-organization).

    On first login the extension auto-selects this org as active, so the user's
    token carries `active_organization` from the start.
    """
    orgs = get_orgs_client()

    # 1. Uniqueness check
    try:
        existing = await orgs.find_user(username=user_data.username)
        if not existing:
            existing = await orgs.find_user(email=user_data.email)
    except KeycloakOrgsError as e:
        logger.error(f"❌ Signup precheck failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authentication service unavailable",
        )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this username or email already exists",
        )

    org_display_name = f"{user_data.firstName} {user_data.lastName}'s Organization"

    try:
        # 2. Create the Keycloak user
        user_id = await orgs.create_user(
            username=user_data.username,
            email=user_data.email,
            first_name=user_data.firstName,
            last_name=user_data.lastName,
            password=user_data.password,
        )
        logger.info(f"✅ User created: {user_data.username} ({user_id})")

        # 3. Create their personal organization (unique machine name + friendly display name)
        org_machine_name = f"{user_data.username}-{user_id[:8]}".lower()
        org_id = await orgs.create_org(name=org_machine_name, display_name=org_display_name)

        # 4. Add as member and grant admin (manage-organization)
        await orgs.add_member(org_id, user_id)
        await orgs.make_admin(org_id, user_id)
        # Register the System Owner custom role up front so it's ready the
        # moment this admin invites one or promotes a member.
        await orgs.ensure_org_role(
            org_id, SYSTEM_OWNER_ROLE, "Can upload documents and see all organization documents"
        )
        logger.info(f"✅ Personal org {org_id} created; {user_data.username} is its admin")

    except KeycloakOrgsError as e:
        logger.error(f"❌ Signup failed: {e}")
        if e.status_code == 409:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this username or email already exists",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create account: {e.message}",
        )

    return SignupResponse(
        id=user_id,
        username=user_data.username,
        email=user_data.email,
        firstName=user_data.firstName,
        lastName=user_data.lastName,
        organization_id=org_id,
        organization_name=org_display_name,
        message="Account created successfully. You can now login.",
    )


@router.post("/login", response_model=LoginResponse)
async def login(credentials: LoginRequest):
    """
    Authenticate user and return access token
    """
    try:
        keycloak_openid = get_keycloak_client()

        # Exchange username/password for tokens
        token_response = keycloak_openid.token(
            username=credentials.username,
            password=credentials.password
        )

        logger.info(f"✅ User logged in: {credentials.username}")

        return LoginResponse(
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            token_type="bearer",
            expires_in=token_response["expires_in"]
        )

    except Exception as e:
        logger.warning(f"⚠️ Login failed for {credentials.username}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )


@router.get("/me", response_model=UserInfoResponse)
async def get_current_user_info(context: dict = Depends(get_current_context)):
    """
    Get the current user, including their active organization and their role
    in it ("admin" | "user"). The frontend uses `role` to hide admin-only UI.
    """
    return UserInfoResponse(
        id=context["id"],
        username=context["username"],
        email=context["email"],
        firstName=context.get("firstName"),
        lastName=context.get("lastName"),
        email_verified=context.get("email_verified", False),
        roles=context.get("realm_roles", []),
        organization_id=context.get("organization_id"),
        organization_name=context.get("organization_name"),
        role=context.get("role"),
    )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(token_request: RefreshTokenRequest):
    """
    Refresh an expired access token
    """
    try:
        keycloak_openid = get_keycloak_client()

        # Exchange refresh token for new access token
        token_response = keycloak_openid.refresh_token(token_request.refresh_token)

        logger.info("✅ Token refreshed")

        return LoginResponse(
            access_token=token_response["access_token"],
            refresh_token=token_response["refresh_token"],
            token_type="bearer",
            expires_in=token_response["expires_in"]
        )

    except Exception as e:
        logger.warning(f"⚠️ Token refresh failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )


@router.post("/logout")
async def logout(token_request: RefreshTokenRequest):
    """
    Logout user and invalidate refresh token
    """
    try:
        keycloak_openid = get_keycloak_client()
        keycloak_openid.logout(token_request.refresh_token)
        logger.info("✅ User logged out")
        return {"message": "Logged out successfully"}

    except Exception as e:
        logger.error(f"❌ Logout failed: {str(e)}")
        return {"message": "Logout completed"}
