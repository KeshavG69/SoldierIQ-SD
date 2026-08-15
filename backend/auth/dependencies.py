"""
Authentication dependencies for FastAPI endpoints.
Provides JWT token validation.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from auth import config
from auth.database import get_mongodb_client


security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    """
    Get current user from JWT token.

    Validates JWT token and returns user dict.

    Args:
        credentials: HTTP Bearer token from Authorization header

    Returns:
        User document dict with _id, email, firstName, lastName

    Raises:
        HTTPException 401: If token is invalid, expired, or user not found
    """
    token = credentials.credentials

    try:
        # Decode JWT token
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.ALGORITHM])
        email: str = payload.get("sub")

        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing email"
            )

        # Get user from database
        users_collection = get_mongodb_client().get_users_collection()
        user = users_collection.find_one({"email": email})

        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )

        return user

    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}"
        )


async def get_current_user_id(
    current_user: dict = Depends(get_current_user)
) -> str:
    """
    Get current user's ID.

    Convenience dependency for endpoints that only need user_id.

    Args:
        current_user: User dict from get_current_user dependency

    Returns:
        User's ID as string
    """
    return str(current_user["_id"])
