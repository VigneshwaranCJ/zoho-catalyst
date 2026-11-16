import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.core.rbac import Permission


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    organization_slug: str | None = Field(default=None, max_length=63)


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    display_name: str
    role: str
    permissions: list[Permission]


class AuthResponse(BaseModel):
    user: MeResponse
    csrf_token: str
    access_token_expires_at: str
