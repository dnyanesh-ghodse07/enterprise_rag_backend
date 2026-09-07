from functools import lru_cache
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Each field maps to an environment variable of the same name (uppercase).
    Example: 'app_name' → APP_NAME environment variable
    """
    # ─── Application ───────────────────────────────────────────────
    app_name: str = "Cognix"
    app_version: str = "0.1.0"
    debug: bool = False  # NEVER True in production!
    environment: str = "development"  # development, staging, production

    # ─── API ───────────────────────────────────────────────────────
    api_prefix: str = "/api/v1"
    allowed_origins: list[str] = [
        "http://localhost:3000",  # Next.js dev server
        "http://localhost:8000",  # FastAPI docs
    ]

    # ─── Database ──────────────────────────────────────────────────
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    database_url: str = "postgresql+asyncpg://cognix:cognix_dev@localhost:5434/cognix"
    database_pool_size: int = 20       # Max connections in the pool
    database_max_overflow: int = 10    # Extra connections allowed beyond pool_size
    database_pool_timeout: int = 30    # Seconds to wait for a connection

    # ─── Redis ─────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_seconds: int = 3600  # Default cache TTL: 1 hour

     # ─── Authentication ────────────────────────────────────────────
    secret_key: str = "CHANGE-ME-IN-PRODUCTION-USE-OPENSSL-RAND"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # ─── OpenAI ────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_max_tokens: int = 4096
    openai_temperature: float = 0.1  # Low = more deterministic

    # ─── Qdrant ────────────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "cognix_documents"

    # ─── Logging ───────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"  # "json" for production, "text" for development

    # ─── Rate Limiting ─────────────────────────────────────────────
    rate_limit_per_minute: int = 60
    
    model_config = SettingsConfigDict(
        env_file=".env",           # Read from .env file
        env_file_encoding="utf-8",
        case_sensitive=False,      # APP_NAME and app_name both work
        extra="ignore",            # Don't fail on unknown env vars
    )
    @field_validator("openai_api_key")
    def validate_openai_api_key(cls, v: str) -> str:
        if not v.startswith("sk-"):
            raise ValueError("OpenAI API key must start with 'sk-'")
        return v

    @model_validator(mode="after")
    def validate_environment(self) -> "Settings":
        if self.environment == "production" and self.openai_api_key == "":
            raise ValueError("OpenAI API key must be set in production")
        return self


@lru_cache()  # Singleton pattern — only creates Settings once
def get_settings() -> Settings:
    """
    Returns the application settings.
    
    Uses @lru_cache to ensure we only read env vars once.
    This is important because:
    1. Reading env vars repeatedly is wasteful
    2. Settings should be immutable during the app's lifetime
    3. If we read them multiple times, we might get inconsistent values
    if someone changes an env var while the app is running
    """
    return Settings()
