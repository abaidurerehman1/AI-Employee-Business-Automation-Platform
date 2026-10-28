import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.auth import MembershipRole


class MessageResponse(BaseModel):
    message: str


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=12, max_length=128)
    organization_name: str = Field(min_length=2, max_length=150)

    @field_validator("full_name", "organization_name", mode="before")
    @classmethod
    def trim_name(cls, value):
        return value.strip() if isinstance(value, str) else value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


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
    owner_user_id: uuid.UUID | None = None


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
    is_active: bool = True


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    full_name: str = Field(min_length=2, max_length=120)


class PasswordInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)


class OrganizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=150)


class MemberInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: MembershipRole
    is_active: bool


class OwnershipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: uuid.UUID
    current_password: str = Field(min_length=1, max_length=128)
