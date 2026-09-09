import logging
from app.schemas.auth import UserRegister, TokenResponse, PasswordChange
from app.core.security import (
  hash_password,
  verify_password,
  create_access_token,
  create_refresh_token,
  decode_token,
  hash_token,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from datetime import datetime, timezone, timedelta
from uuid import UUID

from app.config import get_settings
from app.models import User, Tenant, RefreshToken, UserRole
from app.core.exceptions import (AuthenticationError, ValidationError, NotFoundError)

logger = logging.getLogger(__name__)
settings = get_settings()

class AuthService:
  """
  Authentication Service
      WHY A CLASS (not module-level functions):
    - Encapsulates dependencies (database session)
    - Easy to mock in tests (replace with fake AuthService)
    - Can hold state if needed (caches, counters)
    - Follows the Service pattern common in enterprise apps
  """

  def __init__(self, db: AsyncSession):
    """
    Initialise with the db session

    The session is injected by FastAPI's dependency system:
          auth_service = AuthService(db=Depends(get_session))
    """
    self.db = db

  async def register(self, data: UserRegister) -> TokenResponse:
      """
      Register a new user and their organization.
          
      This creates:
      1. A new Tenant (organization)
      2. A new User (admin of that organization)
      3. An access token + refresh token pair
      
      BUSINESS RULES:
      - Email must not already be registered
      - Tenant slug must be unique
      - First user of a tenant is always an admin
      - Password is hashed before storage
      
      TRANSACTION:
      Everything happens in one database transaction.
      If ANY step fails, NOTHING is committed.
      This prevents orphan tenants (tenant created but user creation failed).
      """

      # Check if email already exists
      existing_user = await self.db.execute(
        select(User).where(User.email == data.email)
      )
      if existing_user.scalar_one_or_none():
          raise ValidationError(
            message="Email already registered",
            details={"field": "email"}
          )

      # Check tenant slug uniqueness
      existing_tenant = await self.db.execute(
        select(Tenant).where(Tenant.slug == data.tenant.slug)
      )
      if existing_tenant.scalar_one_or_none():
          raise ValidationError(
            message="An Organization with this slug already exists",
            details={"field": "tenant.slug"}
          )

      # Create tenant and user in a transaction
      tenant = Tenant(
        name = data.tenant.name,
        slug = data.tenant.slug
      )
      self.db.add(tenant)
      await self.db.flush()  # Get tenant.id before committing
      # flush() vs commit():
      # flush() sends SQL to the database but doesn't commit the transaction
      # We need tenant.id to create the user, but we don't want to commit
      # until everything succeeds

      # Create user
      user = User(
        email = data.email,
        full_name = data.full_name,
        hashed_password = hash_password(data.password),
        tenant_id = tenant.id,
        role = UserRole.ADMIN  # First user is always admin
      )
      self.db.add(user)
      await self.db.flush()  # Commit both tenant and user together

      # Generate tokens
      access_token = create_access_token(
        user_id=user.id, 
        tenant_id=tenant.id, 
        role=user.role.value
      )
      refresh_token_str = create_refresh_token(user_id=user.id)

      # Store refresh token in database (hashed)
      refresh_token = RefreshToken(
        user_id = user.id,
        token_hash = hash_token(refresh_token_str),
        expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
      )
      self.db.add(refresh_token)

      # commit everything (tenant, user, refresh token) in one transaction
      await self.db.commit()

      return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token_str,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60
      )

  async def login(
    self,
    email: str,
    password: str,
    ip_address: str | None = None,
    user_agent: str | None = None
    ) -> TokenResponse:
    """
    Authenticate a user and return tokens.

    SECURITY MEASURES:
      1. Same error message for "user not found" and "wrong password"
          → Prevents email enumeration attacks
          → Attacker can't determine if an email is registered
      2. Constant-time password comparison
          → Prevents timing attacks
      3. Check user is active
          → Disabled users can't log in
      4. Check tenant is active
          → Suspended organizations can't access the system
      5. Update last_login_at
          → Security monitoring: detect dormant accounts
    """
    # Fetch user by email
    result = await self.db.execute(
      select(User).where(User.email == email)
    )
    user = result.scalar_one_or_none()

    # Same error message for "user not found" and "wrong password"
    if user is None:
      logger.warning(
        "auth.login.failure",
        extra={
            "email": email,
            "ip_address": ip_address,
            "reason": "user_not_found",
        },
      )
      raise AuthenticationError(
        message="Invalid email or password",
      )

    # verify password (Argon2 password verification) 
    if not verify_password(password, user.hashed_password):
      logger.warning(
        "auth.login.failure",
        extra={
            "email": email,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "reason": "invalid_password",
        },
      )
      raise AuthenticationError(
        message="Invalid email or password",
      )
    
    # Check user is active
    if not user.is_active:
      logger.warning(
        "auth.login.failure",
        extra={
            "email": email,
            "ip_address": ip_address,
            "reason": "account_disabled",
        },
      )
      raise AuthenticationError(
        message="User account is disabled. Contact support.",
      )
    
    # Check tenant is active
    if not user.tenant.is_active:
      logger.warning(
        "auth.login.failure",
        extra={
            "email": email,
            "ip_address": ip_address,
            "reason": "tenant_suspended",
        },
      )
      raise AuthenticationError(
        message="Organization is suspended. Contact support.",
      )
    
    # generate tokens
    access_token = create_access_token(
      user_id=user.id,
      tenant_id=user.tenant_id,
      role=user.role.value
    )
    refresh_token_str = create_refresh_token(user_id=user.id)

    # store refresh token
    from datetime import timedelta

    refresh_token_obj = RefreshToken(
      user_id=user.id,
      token_hash=hash_token(refresh_token_str),
      expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    )

    self.db.add(refresh_token_obj)

    # update last login
    user.last_login_at = datetime.now(timezone.utc)

    await self.db.commit()

    # logging
    logger.info("auth.login.success", extra={
      "user_id": user.id,
      "tenant_id": user.tenant_id,
      "ip_address": ip_address,
      "user_agent": user_agent

    })

    return TokenResponse(
      access_token=access_token,
      refresh_token=refresh_token_str,
      token_type="bearer",
      expires_in=settings.access_token_expire_minutes * 60
    )

  async def refresh_token(
    self,
    refresh_token_str: str,
    ip_address: str | None = None,
    ) -> TokenResponse:
    """
      Exchange a refresh token for new access + refresh tokens.
      
      REFRESH TOKEN ROTATION:
      1. Verify the refresh token (signature + expiration)
      2. Find the token in the database (by hash)
      3. Check it hasn't been revoked
      4. Generate new access + refresh tokens
      5. Revoke the old refresh token
      6. Store the new refresh token
      
      WHY ROTATION:
      If a refresh token is stolen, the attacker can use it once.
      When the real user tries to use the (now-revoked) token,
      we detect the reuse and revoke ALL tokens for that user.
    """

    from datetime import timedelta
    from jose import JWTError

    # verify token signature and expiration
    try:
      payload = decode_token(refresh_token_str)
    except JWTError:
      raise AuthenticationError(
        message="Invalid refresh token",
      )
    
    if payload.get("type") != "refresh":
      raise AuthenticationError(
        message="Invalid token type",
      )
    
    user_id = payload.get("user_id")
    if not user_id:
      raise AuthenticationError(
        message="Invalid token payload",
      )
    
    # find token in database
    token_hash = hash_token(refresh_token_str)
    result = await self.db.execute(
      select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )

    stored_token = result.scalar_one_or_none()

    if stored_token is None:
      # Token not found - possible theft
      # the original token was revoked or never existed
      # Revoke all tokens for this user as a security measure
      logger.critical("auth.security.token_reuse_detected", extra={
        "user_id": user_id,
        "token_id": token.id,
        "ip_address": ip_address
      })
      await self._revoke_all_tokens_for_user(UUID(user_id))
      raise AuthenticationError(
        message="Token reuse detected. All sessions revoked. Please log in again.",
      )

    if not stored_token.is_valid:
      # Token has been revoked
      raise AuthenticationError(
        message="Refresh token has been revoked. Please log in again.",
      )
    
    result = await self.db.execute(
      select(User).where(User.id == UUID(user_id))
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
      raise AuthenticationError(
        message="User account is disabled. Contact support.",
      )
    
    # Generate new tokens
    new_access_token = create_access_token(
      user_id=user.id,
      tenant_id=user.tenant_id,
      role=user.role.value
    )

    new_refresh_token_str = create_refresh_token(
      user_id=user.id
    )

    # store new refresh token
    new_refresh_token_obj = RefreshToken(
      token_hash=hash_token(new_refresh_token_str),
      user_id=user.id,
      expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    )

    self.db.add(new_refresh_token_obj)
    await self.db.flush()  # flush to get new token id

    # revoke old refresh token
    stored_token.is_revoked = True
    stored_token.revoked_at = datetime.now(timezone.utc)
    stored_token.replaced_by_id = new_refresh_token_obj.id

    await self.db.commit()

    logger.info("auth.token.refresh", extra={
      "user_id": user_id,
      "old_token_id": stored_token.id,
      "new_token_id": new_refresh_token_obj.id
    })

    return TokenResponse(
      access_token=new_access_token,
      refresh_token=new_refresh_token_str,
      token_type="bearer",
      expires_in=settings.access_token_expire_minutes * 60
    )

  async def logout(self, refresh_token_str: str) -> None:
    """
      Revoke a refresh token (logout).
      
      Note: The access token is still valid until it expires.
      This is a trade-off of stateless JWTs — you can't truly
      "invalidate" an access token without a blacklist.
      
      MITIGATIONS:
      - Short access token lifetime (30 min)
      - For immediate invalidation, maintain a Redis blacklist
        of revoked access tokens (check on every request)
      - We'll implement this in Day 14 (Caching & Operations)
      """
    token_hash = hash_token(refresh_token_str)
    result = await self.db.execute(
      select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored_token = result.scalar_one_or_none()

    if stored_token and not stored_token.is_revoked:
      stored_token.is_revoked = True
      stored_token.revoked_at = datetime.now(timezone.utc)
      await self.db.commit()

  async def change_password(self, user, current_password, new_password) -> None:
    print("cp---------", current_password)
    print("np---------", new_password)
    """
    Change the user's password after verifying the current password.

    Steps:
    - Verify provided current_password against stored hash
    - Update the user's hashed_password with the new password
    - Revoke all existing refresh tokens for this user (force re-login)
    - Commit the transaction and log the change
    """

    # Verify the current password matches the stored hash
    if not verify_password(current_password, user.hashed_password):
      logger.warning("auth.password.change.failure", extra={
        "user_id": getattr(user, "id", None)
      })
      raise AuthenticationError(
        message="Current password is incorrect",
      )

    if not new_password or len(new_password) < 8:
      print("-----------new password", new_password)
      raise ValidationError(message="New password too short")
    # Hash and update the new password
    user.hashed_password = hash_password(new_password)

    # Revoke all refresh tokens so existing sessions must re-authenticate
    await self._revoke_all_tokens_for_user(user.id)

    await self.db.commit()

    logger.info("auth.password.change.success", extra={
      "user_id": user.id
    })

  async def _revoke_all_tokens_for_user(self, user_id: UUID) -> None:
    """
    Revoke all refresh tokens for a user.
    
    This is called when token reuse is detected, as a security measure.
    """
    result = await self.db.execute(
      select(RefreshToken).where(
        RefreshToken.user_id == user_id, 
        RefreshToken.is_revoked == False)
    )
    tokens = result.scalars().all()
    now = datetime.now(timezone.utc)

    for token in tokens:
      token.is_revoked = True
      token.revoked_at = datetime.now(timezone.utc)

    await self.db.commit()