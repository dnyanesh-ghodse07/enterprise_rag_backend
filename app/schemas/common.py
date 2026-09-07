"""
Common schemas used across the application.

WHY SEPARATE COMMON SCHEMAS:
- Pagination, error responses, and health checks are used everywhere
- Defining them once prevents inconsistency
- Changes propagate to all endpoints automatically
"""

from datetime import datetime
from typing import Any, Generic, TypeVar
from pydantic import BaseModel, Field

# TypeVar lets us create generic schemas
# PaginatedResponse[Document] and PaginatedResponse[User] 
# have different item types but the same structure
T = TypeVar("T")

class ErrorDetails(BaseModel):
    """
    Standard error response body.
    
    Every API error returns this exact shape.
    This makes frontend error handling trivial:
    
        if (response.error) {
            showToast(response.error.message);
            console.error(response.error.code);
        }
    """

    code: str = Field(..., description="Machine-readable error code", examples=["DOCUMENT_NOT_FOUND"])
    message: str = Field(..., description="Human-readable error message", examples=["Document with ID 42 not found"])
    details: dict[str, Any] = Field(default_factory=dict, description="Additional error context")

class ErrorResponse(BaseModel):
    """Wrapper for error responses."""
    error: ErrorDetails

class PaginatedResponse(BaseModel, Generic[T]):
    """
    Standard paginated response wrapper.
    
    WHY PAGINATION:
    - Never return unbounded lists
    - If a tenant has 100,000 documents, returning all at once would:
      1. Crash the server (memory)
      2. Crash the client (rendering)
      3. Waste bandwidth
      4. Take forever
    
    PAGINATION STRATEGIES:
    
    1. Offset-based (our choice):
       GET /documents?page=3&size=20
       → Skip 40, take 20
       ✅ Simple, frontend can jump to any page
       ❌ Slow for large offsets (PostgreSQL must scan + skip)
    
    2. Cursor-based:
       GET /documents?cursor=eyJpZCI6MTAwfQ==&size=20
       → Start after document with id=100, take 20
       ✅ Consistent performance regardless of page number
       ❌ Can't jump to page 50
    
    We use offset-based for simplicity. If performance degrades
    at scale, we'd switch to cursor-based.
    """
    items: list[T] = Field(default_factory=list, description="List of items on this page")
    total: int = Field(..., description="Total number of items across all pages")
    page: int = Field(..., description="Current page number (1-indexed)")
    size: int = Field(..., description="Number of items per page")
    pages: int = Field(..., description="Total number of pages")

class HealthResponse(BaseModel):
    """
    Health check response.
    
    WHY HEALTH CHECKS:
    - Kubernetes uses them to decide if a pod is alive (liveness)
    - Load balancers use them to route traffic (readiness)
    - Monitoring systems alert when health degrades
    
    HEALTH vs READINESS:
    - Health: "Is the process running?" → /health
    - Readiness: "Can it serve traffic?" → /ready
      (process might be up but database is down)
    """
    status: str = Field(..., description="Overall system status", examples=["healthy"])
    version: str = Field(..., description="Application version", examples=["0.1.0"])
    environment: str = Field(..., description="Current environment", examples=["development"])
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    checks: dict[str, str] = Field(
        default_factory=dict,
        description="Individual component health checks",
        examples=[{"database": "connected", "redis": "connected", "qdrant": "connected"}],
    )