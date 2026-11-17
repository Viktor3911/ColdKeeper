"""Alembic environment (async PostgreSQL). The URL comes from the application settings, never from alembic.ini."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from backend.adapters.db.models import Base
from backend.settings import Settings

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    """Tests pass the URL in ``config.attributes``; otherwise ``COLDKEEPER_DATABASE_URL`` / ``.env``."""
    url = config.attributes.get("database_url")
    if isinstance(url, str):
        return url
    return Settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Emit SQL without a connection (``alembic upgrade head --sql``)."""
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Connect and migrate."""
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
