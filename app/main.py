from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import CognixError

settings = get_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Everything before 'yield' runs at STARTUP.
    Everything after 'yield' runs at SHUTDOWN.
    
    This replaces the deprecated @app.on_event("startup") pattern.
    
    WHY LIFESPAN:
    - Guarantees cleanup happens even if the app crashes
    - Can share resources between startup and shutdown
    - Modern FastAPI pattern (replaces on_event)
    
    ANALOGY:
    Like opening and closing a restaurant:
    - Before yield: turn on lights, preheat ovens, unlock doors
    - yield: restaurant is OPEN, serve customers
    - After yield: clean kitchen, lock doors, turn off lights
    """
    # ═══════════════════════════════════════════════════════════
    # STARTUP
    # ═══════════════════════════════════════════════════════════
    print(f"🚀 Starting {settings.app_name} v{settings.app_version}")
    print(f"📍 Environment: {settings.environment}")
    print(f"🐛 Debug mode: {settings.debug}")
    
    # In future milestones, we'll add:
    # - Database connection verification
    # - Redis connection
    # - Qdrant collection creation
    # - Cache warming
    
    yield  # ← App is running and serving requests
    
    # ═══════════════════════════════════════════════════════════
    # SHUTDOWN
    # ═══════════════════════════════════════════════════════════
    print(f"👋 Shutting down {settings.app_name}")
    
    # In future milestones, we'll add:
    # - Close database connection pool
    # - Close Redis connection
    # - Flush pending logs

def create_app() -> FastAPI:
    """
    Application factory function.
    
    Returns a fully configured FastAPI instance.
    """
    
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Enterprise AI Knowledge Platform — "
            "Secure, multi-tenant RAG system with agentic capabilities."
        ),
        docs_url="/docs" if settings.debug else None,       # Swagger UI
        redoc_url="/redoc" if settings.debug else None,      # ReDoc UI
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
        # Why disable docs in production?
        # 1. Security: API docs reveal your entire API surface
        # 2. Performance: docs endpoints serve JavaScript bundles
        # 3. Professionalism: production users use your client SDK, not Swagger
    )
    
    # ─── Middleware ─────────────────────────────────────────────
    # Middleware runs on EVERY request, in order.
    # Think of it as a pipeline of filters:
    # Request → [CORS] → [Logging] → [Auth] → Handler → Response
    
    # CORS: Cross-Origin Resource Sharing
    # Without this, your Next.js frontend (localhost:3000) can't call
    # your FastAPI backend (localhost:8000) because browsers block
    # cross-origin requests by default (Same-Origin Policy).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,   # Allow cookies
        allow_methods=["*"],      # Allow all HTTP methods
        allow_headers=["*"],      # Allow all headers
    )
    
    # ─── Exception Handlers ────────────────────────────────────
    # These catch exceptions and convert them to JSON responses.
    # Without these, FastAPI returns its default error format,
    # which is different from our standard ErrorResponse.

    @app.exception_handler(CognixError)
    async def cognix_error_handler(request: Request, exc: CognixError):
        """
        Handle all CognixError subclasses.
        
        Because all our custom exceptions inherit from CognixError,
        this ONE handler catches AuthenticationError, NotFoundError, etc.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
    
    @app.exception_handler(Exception)
    async def general_error_handler(request: Request, exc: Exception):
        """
        Catch-all for unexpected errors.
        
        This is the "safety net." If any unhandled exception occurs,
        we return a generic 500 error instead of exposing a stack trace.
        
        In production, this logs the full stack trace for debugging
        but returns a sanitized message to the client.
        """
        # TODO: Add proper logging here (Day 14)
        import traceback
        traceback.print_exc()  # Print to server logs
        
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "An unexpected error occurred. Please try again later.",
                    "details": {"type": type(exc).__name__} if settings.debug else {},
                }
            },
        )
    
    @app.get('/')
    async def root():
        return {"message": "Welcome to the Cognix API", "docs": '/docs'}

    # ─── Register Routes ───────────────────────────────────────
    from app.api.router import api_router 
    app.include_router(api_router, prefix=settings.api_prefix)
    
    return app


# Create the app instance
# This is what uvicorn runs: uvicorn app.main:app
app = create_app()

