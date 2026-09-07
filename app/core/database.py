"""
Database connection and session management.

WHY THIS EXISTS:
- Manages the database connection pool
- Provides async sessions for each request
- Ensures connections are properly returned to the pool

INTERNAL MECHANICS:
1. create_async_engine() creates a connection pool
2. Each request gets a session from the pool
3. The session is used to execute queries
4. When the request ends, the session is returned to the pool
5. If the pool is exhausted, requests wait (up to pool_timeout)
6. If pool_timeout is exceeded, the request fails with an error

CONNECTION POOL LIFECYCLE:
┌──────────┐    get_session()    ┌──────────┐
│          │ ──────────────────► │          │
│   Pool   │                     │  Session │ ← Used by request handler
│  (idle   │ ◄────────────────── │          │
│  conns)  │    session.close()  └──────────┘
└──────────┘
"""

from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from app.config import get_settings


settings = get_settings()

# SSL is required by Neon, but local Postgres usually runs without TLS.
# Only enable it for remote/production URLs so localhost development keeps working.
# You can also override this with the DATABASE_URL itself by including sslmode=require.
database_url = settings.database_url.lower()
connect_args = {}
if (
    settings.environment == "production"
    or "neon.tech" in database_url
    or "sslmode=require" in database_url
    or "ssl=true" in database_url
):
    connect_args = {"ssl": "require"}

# ─── Create the async engine ──────────────────────────────────────
# The engine manages the connection pool to PostgreSQL.
# Think of it as the "parking garage" that holds database connections.
engine = create_async_engine(
    settings.database_url,
    
    # Pool configuration
    pool_size=settings.database_pool_size,        # Normal capacity: 20 connections
    max_overflow=settings.database_max_overflow,   # Emergency capacity: +10 connections
    pool_timeout=settings.database_pool_timeout,   # Wait max 30 seconds for a connection
    pool_recycle=3600,  # Recycle connections every hour (prevents stale connections)
    pool_pre_ping=True,  # Test connection before using it (handles database restarts)
    connect_args=connect_args,
    
    # Logging
    echo=settings.debug,  # Log SQL queries in debug mode (NEVER in production!)
)

# ─── Create session factory ───────────────────────────────────────
# A session factory creates new sessions.
# Think of it as the "ticket machine" that gives you a parking ticket.
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Don't expire objects after commit
    # Why expire_on_commit=False?
    # By default, SQLAlchemy "expires" all loaded objects after commit,
    # meaning the next access triggers a new query. In async code, this
    # causes "greenlet_spawn" errors. Setting this to False prevents that.
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides a database session for each request.
    
    Usage in FastAPI:
        @router.get("/items")
        async def get_items(session: AsyncSession = Depends(get_session)):
            result = await session.execute(select(Item))
            return result.scalars().all()
    
    The 'yield' pattern ensures the session is ALWAYS closed,
    even if the request handler raises an exception.
    This is called a "context manager" pattern.
    
    WHY YIELD AND NOT RETURN:
    - yield pauses the function, gives the session to the caller
    - The caller (FastAPI) uses the session
    - When the request ends, execution resumes after yield
    - The finally block closes the session
    - This guarantees cleanup, like a try/finally
    """
    session = async_session_factory()
    try:
        yield session
    finally:
        await session.close()


async def init_db() -> None:
    """
    Initialize the database connection on startup.
    
    This is called once when the application starts.
    It verifies that the database is reachable.
    If not, the app should fail LOUDLY at startup,
    not silently when the first request comes in.
    """
    async with engine.begin() as conn:
        # Just verify connectivity — actual schema creation
        # is handled by Alembic migrations
        await conn.execute(
            # Simple query to verify the connection works
            # text() wraps a raw SQL string
            __import__("sqlalchemy").text("SELECT 1")
        )
