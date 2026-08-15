from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserSignup(BaseModel):
    firstName: str
    lastName: str
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: str
    firstName: str
    lastName: str
    email: str
    organization_id: Optional[str] = None
    createdAt: datetime


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    email: Optional[str] = None
