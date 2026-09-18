from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.exceptions import AuthenticationError, ValidationError
from app.core.security import create_refresh_token, hash_password, hash_token
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant
from app.models.user import User, UserRole
from app.schemas.auth import UserRegister
from app.services.auth_service import AuthService


@pytest.mark.asyncio
async def test_register_creates_tokens_and_commits() -> None:
    db = MagicMock()
    db.execute = AsyncMock()
    db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: None),
        MagicMock(scalar_one_or_none=lambda: None),
    ]
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    payload = UserRegister(
        email="alice@acme.com",
        password="StrongPass123",
        full_name="Alice Johnson",
        tenant={
            "name": "Acme Corporation",
            "slug": "acme-corp",
        },
    )

    result = await AuthService(db).register(payload)

    assert result.access_token
    assert result.refresh_token
    assert result.token_type == "bearer"
    assert result.expires_in > 0
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_login_rejects_invalid_password() -> None:
    tenant = Tenant(
        id=uuid4(),
        name="Acme Corporation",
        slug="acme-corp",
        is_active=True,
    )
    user = User(
        id=uuid4(),
        email="bob@acme.com",
        full_name="Bob Builder",
        hashed_password=hash_password("StrongPass123"),
        tenant_id=tenant.id,
        role=UserRole.ADMIN,
        is_active=True,
        tenant=tenant,
    )

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

    with pytest.raises(AuthenticationError, match="Invalid email or password"):
        await AuthService(db).login("bob@acme.com", "WrongPassword123")


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email() -> None:
    tenant = Tenant(
        id=uuid4(),
        name="Acme Corporation",
        slug="acme-corp",
        is_active=True,
    )
    user = User(
        id=uuid4(),
        email="alice@acme.com",
        full_name="Alice Johnson",
        hashed_password=hash_password("StrongPass123"),
        tenant_id=tenant.id,
        role=UserRole.ADMIN,
        is_active=True,
        tenant=tenant,
    )

    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: user))

    payload = UserRegister(
        email="alice@acme.com",
        password="StrongPass123",
        full_name="Alice Johnson",
        tenant={
            "name": "Acme Corporation",
            "slug": "acme-corp",
        },
    )

    with pytest.raises(ValidationError, match="Email already registered"):
        await AuthService(db).register(payload)


@pytest.mark.asyncio
async def test_refresh_token_rotates_and_returns_new_tokens() -> None:
    user = User(
        id=uuid4(),
        email="charlie@acme.com",
        full_name="Charlie Brown",
        hashed_password=hash_password("StrongPass123"),
        tenant_id=uuid4(),
        role=UserRole.ADMIN,
        is_active=True,
    )
    old_token = create_refresh_token(user.id)
    stored_token = RefreshToken(
        id=uuid4(),
        user_id=user.id,
        token_hash=hash_token(old_token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        is_revoked=False,
    )

    db = MagicMock()
    db.execute = AsyncMock(
        side_effect=[
            MagicMock(scalar_one_or_none=lambda: stored_token),
            MagicMock(scalar_one_or_none=lambda: user),
        ]
    )
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    result = await AuthService(db).refresh_token(old_token)

    assert result.access_token
    assert result.refresh_token != old_token
    assert result.token_type == "bearer"
    assert stored_token.is_revoked is True
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_logout_revokes_refresh_token() -> None:
    token = create_refresh_token(uuid4())
    stored_token = RefreshToken(
        id=uuid4(),
        user_id=uuid4(),
        token_hash=hash_token(token),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
        is_revoked=False,
    )

    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: stored_token)
    )
    db.commit = AsyncMock()

    await AuthService(db).logout(token)

    assert stored_token.is_revoked is True
    assert stored_token.revoked_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_password_updates_hash_and_revokes_tokens() -> None:
    tenant = Tenant(
        id=uuid4(),
        name="Acme Corporation",
        slug="acme-corp",
        is_active=True,
    )
    user = User(
        id=uuid4(),
        email="dana@acme.com",
        full_name="Dana Ross",
        hashed_password=hash_password("OldPass123"),
        tenant_id=tenant.id,
        role=UserRole.ADMIN,
        is_active=True,
        tenant=tenant,
    )

    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: MagicMock(all=lambda: []))
    )
    db.commit = AsyncMock()

    await AuthService(db).change_password(user, "OldPass123", "NewPass456")

    assert user.hashed_password != hash_password("OldPass123")
    assert user.hashed_password != ""
    assert db.commit.await_count == 2
