"""
Authentication API endpoints.

ENDPOINTS:
  POST /api/v1/auth/register  → Create account + organization
  POST /api/v1/auth/login     → Authenticate and get tokens
  POST /api/v1/auth/refresh   → Exchange refresh token for new tokens
  POST /api/v1/auth/logout    → Revoke refresh token
  GET  /api/v1/auth/me        → Get current user info

DESIGN PRINCIPLES:
- Thin routes: validate input, call service, format output
- No business logic in routes
- Consistent error responses
- OpenAPI documentation with examples
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.schemas.auth import (
    MessageResponse,
    TokenRefresh,
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter()


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account and organization",
    description=(
        "Creates a new organization (tenant) and the first admin user. "
        "Returns access and refresh tokens for immediate authentication."
    ),
    responses={
        201: {"description": "Account created successfully"},
        422: {"description": "Validation error (duplicate email/slug, weak password)"},
    },
)
async def register(
    data: UserRegister,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """
    Register a new user and organization.
    
    This endpoint is PUBLIC (no authentication required).
    It creates both a tenant and the first admin user.
    
    REQUEST BODY:
    {
        "email": "alice@acme.com",
        "password": "MyStr0ngP@ssword!",
        "full_name": "Alice Johnson",
        "tenant": {
            "name": "Acme Corporation",
            "slug": "acme-corp"
        }
    }
    
    RESPONSE:
    {
        "access_token": "eyJhbGciOiJIUzI1NiJ9...",
        "refresh_token": "eyJhbGciOiJIUzI1NiJ9...",
        "token_type": "bearer",
        "expires_in": 1800
    }
    """
    service = AuthService(db)
    return await service.register(data)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description="Authenticates a user and returns access and refresh tokens.",
    responses={
        200: {"description": "Login successful"},
        401: {"description": "Invalid credentials"},
    },
)
async def login(
    data: UserLogin,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """
    Authenticate and receive tokens.
    
    REQUEST:
    {
        "email": "alice@acme.com",
        "password": "MyStr0ngP@ssword!"
    }
    
    RESPONSE:
    {
        "access_token": "eyJ...",
        "refresh_token": "eyJ...",
        "token_type": "bearer",
        "expires_in": 1800
    }
    
    SECURITY NOTES:
    - Returns same error for "user not found" and "wrong password"
    - Rate limiting should be applied to this endpoint (Day 14)
    - Consider adding CAPTCHA after N failed attempts
    """
    service = AuthService(db)
    return await service.login(data.email, data.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
    description=(
        "Exchange a valid refresh token for new access and refresh tokens. "
        "The old refresh token is immediately invalidated (rotation)."
    ),
    responses={
        200: {"description": "Tokens refreshed successfully"},
        401: {"description": "Invalid or expired refresh token"},
    },
)
async def refresh_token(
    data: TokenRefresh,
    db: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """
    Refresh tokens using token rotation.
    
    REQUEST:
    {
        "refresh_token": "eyJ..."
    }
    
    RESPONSE:
    {
        "access_token": "eyJ... (NEW)",
        "refresh_token": "eyJ... (NEW, old one is revoked)",
        "token_type": "bearer",
        "expires_in": 1800
    }
    """
    service = AuthService(db)
    return await service.refresh_token(data.refresh_token)


@router.post(
    "/logout",
    response_model=MessageResponse,
    summary="Logout (revoke refresh token)",
    description="Revokes the refresh token. The access token remains valid until expiration.",
    responses={
        200: {"description": "Logged out successfully"},
    },
)
async def logout(
    data: TokenRefresh,
    db: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """
    Revoke a refresh token.
    
    NOTE: The access token is still valid until it expires (30 min).
    For immediate access revocation, we'd need a token blacklist
    in Redis (covered in Day 14).
    """
    service = AuthService(db)
    await service.logout(data.refresh_token)
    return MessageResponse(
        message="Successfully logged out",
        detail="Refresh token has been revoked. Access token will expire shortly.",
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user information",
    description="Returns the profile of the currently authenticated user.",
    responses={
        200: {"description": "User profile"},
        401: {"description": "Not authenticated"},
    },
)
async def get_me(user: CurrentUser) -> UserResponse:
    """
    Get the current authenticated user's profile.
    
    This endpoint demonstrates:
    1. Protected route (requires valid JWT)
    2. CurrentUser dependency (auto-resolves user from JWT)
    3. Response model (UserResponse excludes password)
    
    The 'user' parameter is injected by get_current_user dependency.
    If the JWT is invalid, this function NEVER executes.
    """
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role.value,
        is_active=user.is_active,
        tenant_id=user.tenant_id,
        tenant_name=user.tenant.name if user.tenant else None,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )