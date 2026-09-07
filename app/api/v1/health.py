from datetime import datetime,timezone
from fastapi import APIRouter
from fastapi.responses import JSONResponse
import httpx
from redis.asyncio import Redis
from sqlalchemy import text

from app.config import get_settings
from app.core.database import engine
from app.schemas.common import HealthResponse

router = APIRouter()

settings = get_settings()

@router.get(
    "",
    response_model=HealthResponse,
    summary="Basic health check",
    description="Returns the basic health status of the application.",
    responses={
        200:{
            "description": "Application is healthy",
            "content":{
                "application/json":{
                    "example":{
                        "status":"healthy",
                        "name":"Cognix",
                        "version":"0.1.0",
                        "environment":"development",
                        "timestamp":"2023-01-01T00:00:00.000Z",
                        "checks": {}
                    }
                }
            }
        }
    }
)
async def health_check() -> HealthResponse:
    """
    Basic liveness probe.
    
    Returns 200 if the process is running.
    Does NOT check external dependencies.
    
    Used by: Kubernetes liveness probe, uptime monitors.
    """
    return HealthResponse(
        status="healthy",
        name=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
        checks={}
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    summary="Readiness check",
    description="Checks if the application and all its dependencies are ready to serve traffic.",
    responses={
        200: {
            "description": "Application is ready to serve traffic",
        },
        503: {
            "description": "Application is NOT ready (dependency check failed)",
        }
    }
)
async def readiness_check() -> HealthResponse:
    """
    Readiness probe — checks all dependencies.
    
    Checks:
    - Database connectivity
    - Redis connectivity  
    - Qdrant connectivity
    
    If any check fails, returns 503 (Service Unavailable).
    
    Used by: Kubernetes readiness probe, load balancers.
    """
    checks: dict[str, str] = {}
    all_healthy = True
    
    # ─── Database Check ────────────────────────────────────────
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"
        all_healthy = False
    
    # ─── Redis Check ───────────────────────────────────────────
    redis: Redis | None = None
    try:
        redis = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        await redis.ping()
        checks["redis"] = "connected"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"
        all_healthy = False
    finally:
        if redis is not None:
            await redis.aclose()
    
    # ─── Qdrant Check ──────────────────────────────────────────
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            response = await client.get(f"http://{settings.qdrant_host}:{settings.qdrant_port}/healthz")
            response.raise_for_status()
        checks["qdrant"] = "connected"
    except Exception as e:
        checks["qdrant"] = f"error: {str(e)}"
        all_healthy = False
    
    status_code = 200 if all_healthy else 503
    
    response = HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version=settings.app_version,
        environment=settings.environment,
        timestamp=datetime.now(timezone.utc),
        checks=checks,
    )
    
    # Note: To return a non-200 status code with a model,
    # we'd use JSONResponse. For now, this returns 200 always.
    # We'll fix this in a later milestone.
    return JSONResponse(
        status_code=status_code,
        content=response.model_dump(mode='json'),
    )
    
