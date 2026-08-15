from typing import Optional
from datetime import datetime
from bson import ObjectId
from .database import get_mongodb_client
from .models import UserSignup, UserResponse
from .utils import hash_password, verify_password, generate_user_id


class UserCRUD:
    """User CRUD operations"""

    @staticmethod
    def create_user(user_data: UserSignup) -> UserResponse:
        """Create a new user"""
        users_collection = get_mongodb_client().get_users_collection()

        # Check if user already exists
        existing_user = users_collection.find_one({"email": user_data.email})
        if existing_user:
            raise ValueError("User with this email already exists")

        # Create user ID and organization ID
        user_id = generate_user_id()
        organization_id = ObjectId()  # Create a unique organization for the user
        hashed_password = hash_password(user_data.password)
        now = datetime.utcnow()

        user_doc = {
            "_id": user_id,
            "firstName": user_data.firstName,
            "lastName": user_data.lastName,
            "email": user_data.email,
            "password": hashed_password,
            "organization_id": organization_id,
            "createdAt": now,
            "updatedAt": now
        }

        # Insert user into database
        result = users_collection.insert_one(user_doc)

        if result.inserted_id:
            return UserResponse(
                id=str(user_id),
                firstName=user_data.firstName,
                lastName=user_data.lastName,
                email=user_data.email,
                organization_id=str(organization_id),
                createdAt=user_doc["createdAt"]
            )
        else:
            raise Exception("Failed to create user")

    @staticmethod
    def authenticate_user(email: str, password: str) -> Optional[UserResponse]:
        """Authenticate user with email and password"""
        users_collection = get_mongodb_client().get_users_collection()

        # Find user by email
        user_doc = users_collection.find_one({"email": email})
        if not user_doc:
            return None

        # Verify password
        if not verify_password(password, user_doc["password"]):
            return None

        return UserResponse(
            id=str(user_doc["_id"]),
            firstName=user_doc["firstName"],
            lastName=user_doc["lastName"],
            email=user_doc["email"],
            organization_id=str(user_doc.get("organization_id")) if user_doc.get("organization_id") else None,
            createdAt=user_doc["createdAt"]
        )

    @staticmethod
    def get_user_by_email(email: str) -> Optional[UserResponse]:
        """Get user by email"""
        users_collection = get_mongodb_client().get_users_collection()

        user_doc = users_collection.find_one({"email": email})
        if not user_doc:
            return None

        return UserResponse(
            id=str(user_doc["_id"]),
            firstName=user_doc["firstName"],
            lastName=user_doc["lastName"],
            email=user_doc["email"],
            organization_id=str(user_doc.get("organization_id")) if user_doc.get("organization_id") else None,
            createdAt=user_doc["createdAt"]
        )

    @staticmethod
    def get_user_by_id(user_id: str) -> Optional[UserResponse]:
        """Get user by ID"""
        users_collection = get_mongodb_client().get_users_collection()

        user_doc = users_collection.find_one({"_id": ObjectId(user_id)})
        if not user_doc:
            return None

        return UserResponse(
            id=str(user_doc["_id"]),
            firstName=user_doc["firstName"],
            lastName=user_doc["lastName"],
            email=user_doc["email"],
            organization_id=str(user_doc.get("organization_id")) if user_doc.get("organization_id") else None,
            createdAt=user_doc["createdAt"]
        )


def get_user_crud() -> UserCRUD:
    """Get UserCRUD instance"""
    return UserCRUD()
