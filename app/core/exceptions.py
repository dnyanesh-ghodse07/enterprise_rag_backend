"""
Custom exception hierarchy for the application.

WHY A CUSTOM HIERARCHY:
- Python's built-in exceptions (ValueError, KeyError) don't carry
  HTTP-relevant information (status code, error code)
- FastAPI's default error responses are not consistent
- We want EVERY error response to have the same shape:
  {
    "error": {
      "code": "DOCUMENT_NOT_FOUND",
      "message": "Document with ID 42 not found",
      "details": {}
    }
  }

EXCEPTION HIERARCHY:
CognixError (base)
├── AuthenticationError (401)
├── AuthorizationError (403)  
├── NotFoundError (404)
├── ValidationError (422)
├── RateLimitError (429)
├── ExternalServiceError (502)
└── InternalError (500)
"""

from typing import Any

class CognixError(Exception):
    """
    Base exception for all application errors.
    
    Every custom exception inherits from this.
    This lets us catch ALL application errors in one handler:
    
        except CognixError as e:
            return JSONResponse(status_code=e.status_code, ...)
    """

    def __init__(
        self, 
        message: str, 
        code: str = 'INTERNAL_ERROR', 
        status_code: int = 500, 
        details: dict[str, Any] | None = None
    ):
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)

class AuthenticationError(CognixError):
    """User is not authenticated (no token, invalid token, expired token)."""
    def __init(self, message: str = "Authentication required", details: dict[str,Any] | None = None):
        super().__init__(
            message=message,
            code= "AUTHENTICATION_REQUIRED",
            status_code=401,
            details=details
        )

class AuthorizationError(CognixError):
    """User is authenticated but lacks permission for this action."""
    def __init__(self, message: str = "Insufficient persmission", details: dict[str,Any] | None = None):
        super().__init__(
            message=message, 
            code= "FORBIDDEN", 
            status_code=403, 
            details=details
        )

class NotFoundError(CognixError):
    """Requested resource does not exist."""
    
    def __init__(self, resource: str, identifier: Any, details: dict[str, Any] | None = None):
        super().__init__(
            message=f"{resource} with identifier '{identifier}' not found",
            code=f"{resource.upper()}_NOT_FOUND",
            status_code=404,
            details=details,
        )

class ValidationError(CognixError):
    """Request data is invalid."""
    
    def __init__(self, message: str = "Validation error", details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=422,
            details=details,
        )

class RateLimitError(CognixError):
    """User has exceeded the rate limit."""
    
    def __init__(self, message: str = "Rate limit exceeded. Please try again later.", details: dict[str, Any] | None = None):
        super().__init__(
            message=message,
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            details=details,
        )

class ExternalServiceError(CognixError):
    """An external service (OpenAI, Qdrant, etc.) is unavailable or returned an error."""
    
    def __init__(self, service: str, message: str = "", details: dict[str, Any] | None = None):
        super().__init__(
            message=f"External service '{service}' error: {message}",
            code="EXTERNAL_SERVICE_ERROR",
            status_code=502,
            details=details,
        )