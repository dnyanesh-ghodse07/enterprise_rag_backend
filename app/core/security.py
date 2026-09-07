from datetime import datetime, timezone, timedelta
from typing import Any
from uuid import UUID
import hashlib

from jose import jwt, JWTError
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import get_settings

settings = get_settings()

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
  """
  Hash a plain text password using bcrypt.
  
  Args:
      password (str): The plain text password to hash.
      e.g "$2b$12$LJ3m4ys3Lg7E/9hVVfSVcOQYmGhPOAbYso0.jiMSiy5aBxOKaMD.u"
  
  Returns:
      str: The hashed string.

  The returned string contains:
  - The algorithm identifier (e.g., "$2b$")
  - The cost factor (e.g., "12$")
  - The salt (e.g., 22 characters)
  - The hashed password (e.g., 31 characters)

  All of this is needed for verification, thats why we store the entire string, not just the hash
  """
  return password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
  """
  Verify a plain text password against a bcrypt hash.

  Args:
      plain_password (str): The plain text password to verify.
      hashed_password (str): The bcrypt hash to verify against.

  Returns:
      bool: True if the password is correct, False otherwise.

  INTERNAL:
  1. Extract the salt from hashed_password
  2. Hash the plain_password with the same salt and cost factor
  3. Compare the resulting hash with hashed_password
  4. Uses constant-time comparison to prevent timing attacks

  TIMING ATTACK EXPLANATION:
  A naive string comparison 'a' == 'b' returns False immediately when the first character differs.
  This can leak information about the correct password based on how long the comparison takes.
  To prevent this, we use a constant-time comparison function that always takes the same amount of 
  time regardless of how many characters match. 
  This way, an attacker cannot infer any information about the correct
  """
  try:
    return password_hasher.verify(
      hashed_password,plain_password
    )
  except VerifyMismatchError:
    return False


# JWT TOKEN OPERATIONS

def create_access_token(
  user_id: UUID,
  tenant_id: UUID,
  role: str,
  expires_delta: timedelta | None = None) -> str:
  """
  Create a JWT access token for a user.

  Args:
    user_id: The user's UUID
    tenant_id: The tenant's UUID
    role: The user's role (e.g., "viewer", 'editor", "admin",)')
    expires_delta: Optional timedelta for token expiration. Defaults to 15 minutes.

  Returns:
    str: The encoded JWT token as a string.

  TOKEN PAYLOAD:
    {
      "sub": "user:018d5a3c-8b00",      ← Subject (who)
      "user_id": "018d5a3c-8b00",        ← User identifier
      "tenant_id": "018d5a3c-7f00",      ← Tenant identifier
      "role": "editor",                  ← User role
      "type": "access",                  ← Token type
      "exp": 1705312200,                 ← Expiration (Unix timestamp)
      "iat": 1705310400                  ← Issued at
    }
  """

  if expires_delta is None:
      expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
  
  now = datetime.now(timezone.utc)
  expire = now + expires_delta

  payload: dict[str, Any] = {
    "sub": f"user:{user_id}",
    "user_id": str(user_id),
    "tenant_id": str(tenant_id),
    "role": role,
    "type": "access",
    "exp": int(expire.timestamp()),
    "iat": int(now.timestamp())
  }

  return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(
  user_id: UUID,
  expires_delta: timedelta | None = None) -> str:
  """
  Create a JWT refresh token for a user.

  DIFFERENCE FROM ACCESS TOKEN:
  - Longer lifetime (default 7 days vs 30 minutes)
  - Minimal payload (only user_id, no role/tenant info)
  - Only sent to /auth/refresh endpoint
  - Stored (hashed) in the database for revocation
  
  
  WHY MINIMAL PAYLOAD:
  If a user's role change, the new access token (generated 
  on refresh) will pick up the new role from the database.
  The refresh token does not need to carry role/tenant info,
  as it is only used to get a new access token.
  
  """
  if expires_delta is None:
    expires_delta = timedelta(days=settings.refresh_token_expire_days)
  
  now = datetime.now(timezone.utc)
  expire = now + expires_delta

  payload: dict[str, Any] = {
    "sub": f"user:{user_id}",
    "user_id": str(user_id),
    "type": "refresh",
    "exp": int(expire.timestamp()),
    "iat": int(now.timestamp())
  }

  return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict[str, Any]:
  """
  Decode and verify a JWT token.

  Args:
    token: The encoded JWT token string.

  Returns:
    dict: The decoded payload if the token is valid.

  Raises:
      JWTError: If the token is invalid or expired or tampered.
  
  VERIFICATION STEPS:
    1. Split the token into header.payload.signature
    2. Verify the signature using the secret key
     -> If signature does not match, raise JWTError
    3. Decode the payload (base64url decode)
    4. Check the "exp" claim to ensure the token is not expired
      -> If expired, raise JWTError
    5. Return the payload
  """
  try:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    return payload
  except JWTError as e:
    raise JWTError(f"Token verification failed: {str(e)}")


def hash_token(token: str) -> str:
  """
  Hash a refresh token for database storage.

  WHY HASH REFRESH TOKENS:
  - if the database is compromised, attackers cannot use the tokens directly.
  - same principle as password hashing.
  - we use SHA-256(not bcrypt) because :
    -> Refresh tokens are already random (high entropy).
    -> No need for salt (tokens are unique by design).
    -> SHA-256 is fast (we check this on refresh request)
    -> bcrypt would add unnecessary latency.

  BCRYPT vs SHA-256:
  - Passwords: low entropy (humans pick "password123")
   need slow hash to prevent brute force -> bcrypt
  - Tokens: high entropy (cryptographically random)
    -> fast hash like SHA-256 is sufficient

  """
  return hashlib.sha256(token.encode()).hexdigest()