"""
Refresh token model for token rotation and revocation.

WHY STORE REFRESH TOKENS IN THE DATABASE:
- Access tokens are stateless (verified by signature alone)
- Refresh tokens MUST be revocable (for logout, security)
- Storing them allows:
  → Revoking specific sessions
  → Detecting token reuse (theft)
  → Enforcing session limits
  → Audit trail of all sessions

SECURITY: We store a HASH of the token, not the token itself.
If the database is breached, the attacker can't use the tokens.
Same principle as password hashing.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class RefreshToken(BaseModel):
    """
    Stored refresh token for session management.
    
    TOKEN CHAIN (for rotation detection):
    
    Login → Token A
    Refresh → Token B (replaces A, A.replaced_by = B.id)
    Refresh → Token C (replaces B, B.replaced_by = C.id)
    
    If someone uses Token A again:
    1. A is already revoked → token reuse detected!
    2. Follow the chain: A → B → C
    3. Revoke ALL tokens in the chain
    4. Force user to re-login
    """
    __tablename__ = "refresh_tokens"
    
    # ─── Token ────────────────────────────────────────────────
    token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="SHA-256 hash of the refresh token",
    )
    
    # ─── User Relationship ────────────────────────────────────
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="The user this token belongs to",
    )
    
    # ─── Expiration ───────────────────────────────────────────
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this token expires",
    )
    
    # ─── Revocation ───────────────────────────────────────────
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
        comment="Whether this token has been manually revoked",
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this token was revoked",
    )
    
    # ─── Rotation Chain ───────────────────────────────────────
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("refresh_tokens.id"),
        nullable=True,
        comment="ID of the token that replaced this one (rotation chain)",
    )
    
    # ─── Relationships ────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        back_populates="refresh_tokens",
    )
    
    @property
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        from datetime import timezone
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if the token is still usable."""
        return not self.is_revoked and not self.is_expired
    
    def __repr__(self) -> str:
        return f"<RefreshToken(id={self.id}, user_id={self.user_id}, valid={self.is_valid})>"
