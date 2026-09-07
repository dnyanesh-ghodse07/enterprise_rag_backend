"""
Alembic migration environment configuration.
"""

import sys
from pathlib import Path

# This MUST be before any app imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import base first, then models to register tables in metadata
from app.models.base import Base
from app.models.user import User          # noqa: F401
from app.models.tenant import Tenant      # noqa: F401
from app.models.refresh_token import RefreshToken  # noqa: F401

from app.config import get_settings

settings = get_settings()

# this is the Alembic Config object
config = context.config

# override the database URL
config.set_main_option("sqlalchemy.url", settings.database_url)

# This is the metadata object that Alembic uses to detect model changes
target_metadata = Base.metadata

# DEBUG
print(f"DEBUG env.py: tables = {list(target_metadata.tables.keys())}")


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()