"""
FastAPI dependencies for authentication and authorization.

WHAT ARE DEPENDENCIES:
Dependencies are functions that FastAPI calls BEFORE your endpoint handler.
They can:
- Extract data from the request (JWT from header)
- Validate data (verify JWT signature)
- Load data (fetch user from database)
- Enforce rules (check user has required role)

HOW TO USE:
    @router.get("/documents")
    async def list_documents(
        user: User = Depends(get_current_user),  ← Injected!
    ):
        # 'user' is guaranteed to be an authenticated, active User
        # If JWT is invalid, this endpoint never executes

DEPENDENCY CHAIN:
    get_current_user
    └── Extracts JWT from Authorization header
    └── Decodes and verifies JWT
    └── Loads user from database
    └── Verifies user is active
    └── Returns User object

    require_role(UserRole.ADMIN)
    └── Calls get_current_user
    └── Checks user.role >= required role
    └── Returns User object or raises 403
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_token
from app.models.user import User, UserRole

# HTTPBearer extracts the token from the 'Authorization: Bearer <token>' header
# It also adds a "lock" icon in the Swagger UI for authentication
security_scheme = HTTPBearer(
    scheme_name="JWT",
    description="Enter your JWT access token",
    auto_error=True,  # Automatically return 401 if header is missing
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """
    Dependency that returns the current authenticated user.
    
    This is the most important dependency in the application.
    It's used by almost every protected endpoint.
    
    FLOW:
    1. HTTPBearer extracts token from 'Authorization: Bearer <token>'
    2. We decode the JWT and verify its signature
    3. We extract the user_id from the token payload
    4. We load the user from the database
    5. We verify the user is active
    6. We return the User object
    
    If ANY step fails, we raise a 401 Unauthorized error.
    The endpoint handler NEVER executes.
    
    WHY LOAD FROM DATABASE (not just trust the JWT):
    - User might have been deactivated AFTER the token was issued
    - User's role might have changed
    - We need the full User object with tenant relationship
    - Principle of least trust: verify, don't assume
    """
    token = credentials.credentials
    
    # ─── Decode JWT ───────────────────────────────────────────
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
            # WWW-Authenticate header tells the client
            # that Bearer authentication is required
        )
    
    # ─── Validate token type ──────────────────────────────────
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Use an access token, not a refresh token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ─── Extract user ID ─────────────────────────────────────
    user_id_str = payload.get("user_id")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing user_id",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ─── Load user from database ──────────────────────────────
    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ─── Verify user is active ────────────────────────────────
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is disabled",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # ─── Verify tenant is active ──────────────────────────────
    if not user.tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organization account is suspended",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


def require_role(minimum_role: UserRole):
    """
    Dependency factory that creates a role-checking dependency.
    
    USAGE:
        @router.delete("/documents/{id}")
        async def delete_document(
            user: User = Depends(require_role(UserRole.ADMIN)),
        ):
            # Only admins reach this point
    
    HOW IT WORKS:
    This is a "dependency factory" — a function that RETURNS a dependency.
    
    require_role(UserRole.ADMIN) returns a function that:
    1. Calls get_current_user (gets authenticated user)
    2. Checks user.role >= ADMIN
    3. Returns user if authorized, raises 403 if not
    
    WHY A FACTORY:
    We need different role requirements for different endpoints.
    A factory lets us parameterize the dependency:
    - require_role(UserRole.VIEWER)  → anyone authenticated
    - require_role(UserRole.EDITOR)  → editors and admins
    - require_role(UserRole.ADMIN)   → admins only
    """
    async def role_checker(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if not UserRole.has_permission(user.role, minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires {minimum_role.value} role or higher. "
                       f"Your role: {user.role.value}",
            )
        return user
    
    return role_checker


# ─── Convenience type aliases ─────────────────────────────────
# These make endpoint signatures cleaner:
#   async def endpoint(user: CurrentUser):
#   vs
#   async def endpoint(user: Annotated[User, Depends(get_current_user)]):

CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(require_role(UserRole.ADMIN))]
EditorUser = Annotated[User, Depends(require_role(UserRole.EDITOR))]
