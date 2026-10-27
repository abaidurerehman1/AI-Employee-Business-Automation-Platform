import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.auth import MembershipRole


class MessageResponse(BaseModel):
    message: str


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=2, max_length=150)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenRequest(BaseModel):
    token: str = Field(min_length=20)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=128)


class OrganizationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    slug: str
    role: MembershipRole


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: EmailStr
    full_name: str
    is_email_verified: bool


class SessionResponse(BaseModel):
    user: UserResponse
    organizations: list[OrganizationSummary]
    csrf_token: str


class InviteRequest(BaseModel):
    email: EmailStr
    role: MembershipRole = MembershipRole.employee


class InvitationResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: MembershipRole
    expires_at: datetime


class MemberResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: MembershipRole
