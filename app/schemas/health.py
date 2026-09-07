"""
Health check schemas.

Separated from common.py because health checks will grow
to include detailed component statuses, latency measurements, etc.
"""

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """Health status of an individual component."""
    status: str = Field(..., description="Component status", examples=["connected", "disconnected"])
    latency_ms: float | None = Field(None, description="Response time in milliseconds")
    details: str = Field(default="", description="Additional information")


class DetailedHealthResponse(BaseModel):
    """Detailed health response with component-level status."""
    status: str = Field(..., description="Overall status")
    version: str
    environment: str
    components: dict[str, ComponentHealth] = Field(default_factory=dict)

