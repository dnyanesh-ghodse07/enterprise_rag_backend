"""
Authentication request and response schemas.

THESE ARE THE API CONTRACTS:
- Frontend developers read these to know what to send and expect
- FastAPI uses these for automatic validation
- OpenAPI docs are generated from these
- Tests use these to construct valid requests

NAMING CONVENTION:
- *Create: Used in POST requests to create resources
- *Response: Returned in API responses (never include secrets)
- *Update: Used in PUT/PATCH requests
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

def validate_password_strength(v: str) -> str:
    """
        Enforce password complexity rules.
        
        Requirements:
        - At least 8 characters (already enforced by min_length)
        - At least one uppercase letter
        - At least one lowercase letter
        - At least one digit
        
        WHY THESE RULES:
        - Short passwords are easily brute-forced
        - Dictionary words are in rainbow tables
        - Mixing character types exponentially increases the search space
        
        PASSWORD ENTROPY:
        - 8 lowercase letters: 26^8 = 208 billion combos
        - 8 mixed case + digits: 62^8 = 218 trillion combos
        - 1000x harder to crack!
    """
    if not any(c.isupper() for c in v):
        raise ValueError("Password must contain at least one uppercase letter")
    if not any(c.islower() for c in v):
        raise ValueError("Password must contain at least one lowercase letter")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit")
    return v

class TenantCreate(BaseModel):
    """Schema for creating a new tenant during registration."""
    name: str = Field(
        ..., # (...)means required
        min_length=2,
        max_length=255,
        description="Organization name",
        examples=["Acme Corporation"],
    )
    slug: str = Field(
        ...,
        min_length=2,
        max_length=255,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        description="URL-friendly identifier (lowercase, hyphens only)",
        examples=["acme-corp"],
    )
    
    @field_validator("slug")
    @classmethod
    def validate_slug(cls, v: str) -> str:
        """
        Ensure slug is URL-safe.
        
        Valid: "acme-corp", "my-company", "test123"
        Invalid: "Acme Corp", "my_company", "test@123"
        
        WHY VALIDATE:
        Slugs appear in URLs and API paths.
        Invalid characters break routing and cause security issues.
        """
        if not v.replace("-", "").isalnum():
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens")
        return v.lower()

class UserRegister(BaseModel):
    """
    Schema for user registration.
    
    Includes tenant information because registration
    creates both a tenant and the first admin user.
    """
    email: EmailStr = Field(
        ...,
        description="User's email address (will be the login identifier)",
        examples=["alice@acme.com"],
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Password (min 8 characters)",
        examples=["MyStr0ngP@ssword!"],
    )
    full_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="User's display name",
        examples=["Alice Johnson"],
    )
    tenant: TenantCreate = Field(
        ...,
        description="Organization to create",
    )
    
    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return validate_password_strength(v)

class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr = Field(
        ...,
        description="Registered email address",
        examples=["alice@acme.com"],
    )
    password: str = Field(
        ...,
        description="Account password",
        examples=["MyStr0ngP@ssword!"],
    )

class TokenResponse(BaseModel):
    """
    Response returned after successful login or registration.
    
    WHY BOTH TOKENS:
    - access_token: Short-lived, sent with every API request
    - refresh_token: Long-lived, used only to get new access tokens
    - token_type: Always "bearer" (HTTP Bearer Authentication standard)
    """
    access_token: str = Field(..., description="JWT access token (short-lived)")
    refresh_token: str = Field(..., description="JWT refresh token (long-lived)")
    token_type: str = Field(default="bearer", description="Token type (always 'bearer')")
    expires_in: int = Field(..., description="Access token lifetime in seconds")

class TokenRefresh(BaseModel):
    """Schema for refreshing an access token."""
    refresh_token: str = Field(
        ...,
        description="The refresh token received during login",
    )

class UserResponse(BaseModel):
    """
    User information returned in API responses.
    
    NOTICE: No password field!
    NEVER return password hashes in API responses.
    This is why we have separate schemas for DB models
    and API responses.
    """
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    tenant_id: UUID
    tenant_name: str | None = None
    created_at: datetime
    last_login_at: datetime | None = None
    
    model_config = {"from_attributes": True}
    # from_attributes = True:
    # Allows creating UserResponse from a SQLAlchemy User object:
    #   user_obj = await db.get(User, id)
    #   response = UserResponse.model_validate(user_obj)
    # Without this, Pydantic wouldn't know how to read SQLAlchemy attributes.

class MessageResponse(BaseModel):
    """Generic message response."""
    message: str
    detail: str | None = None

class PasswordChange(BaseModel):
    current_password: str = Field(
        ...,
        description="Current Password",
    )
    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New password"
    )
    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return validate_password_strength(v)