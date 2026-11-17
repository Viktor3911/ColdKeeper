"""FastAPI application: routers, error mapping and lifecycle of the composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.composition import Container, build_container
from backend.domain.errors import (
    AuthenticationError,
    ColdKeeperError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ValidationFailedError,
)
from backend.interfaces.http.dependencies import ContainerDep
from backend.interfaces.http.routes import auth, ingest, inventory, journal, monitoring, recipients, sensors
from backend.interfaces.http.schemas import HealthOut, MetaOut
from backend.interfaces.logging_setup import configure_logging
from backend.settings import Settings

_STATUS: dict[type[ColdKeeperError], int] = {
    ValidationFailedError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    NotFoundError: status.HTTP_404_NOT_FOUND,
    PermissionDeniedError: status.HTTP_403_FORBIDDEN,
    ConflictError: status.HTTP_409_CONFLICT,
    AuthenticationError: status.HTTP_401_UNAUTHORIZED,
    RateLimitedError: status.HTTP_429_TOO_MANY_REQUESTS,
}


async def _domain_error(_request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ColdKeeperError)  # noqa: S101 - registered only for this type
    code = next((value for kind, value in _STATUS.items() if isinstance(error, kind)), status.HTTP_400_BAD_REQUEST)
    headers = {"Retry-After": str(error.retry_after_seconds)} if isinstance(error, RateLimitedError) else None
    return JSONResponse({"detail": error.message}, status_code=code, headers=headers)


async def _validation_error(_request: Request, error: Exception) -> JSONResponse:
    """Field names and reasons only: FastAPI's default would echo inputs, including a device token."""
    assert isinstance(error, RequestValidationError)  # noqa: S101 - registered only for this type
    parts = [f"{'.'.join(str(loc) for loc in item['loc'])}: {item['msg']}" for item in error.errors()[:5]]
    return JSONResponse({"detail": "Некорректный запрос: " + "; ".join(parts)}, status_code=422)


def create_app(container: Container, *, owns_container: bool = False) -> FastAPI:
    """Application around an existing container (tests pass one with a controlled clock)."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_container:
            await container.close()

    app = FastAPI(
        title="ColdKeeper API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.container = container
    app.add_exception_handler(ColdKeeperError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    for module in (auth, ingest, inventory, monitoring, sensors, journal, recipients):
        app.include_router(module.router)

    @app.get("/api/v1/health", tags=["system"])
    async def health(current: ContainerDep) -> HealthOut:
        """Liveness with a database round trip."""
        try:
            async with current.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError):
            return HealthOut(status="degraded", database=False)
        return HealthOut(status="ok", database=True)

    @app.get("/api/v1/meta", tags=["system"])
    async def meta(current: ContainerDep) -> MetaOut:
        """Environment facts for the interface."""
        settings = current.settings
        return MetaOut(
            environment=settings.env.value,
            ingest_url=settings.public_url.rstrip("/") + "/api/v1/ingest/unitx?token=<ключ>",
            bot_configured=settings.bot_configured,
            bot_username=settings.telegram_bot_username if settings.bot_configured else None,
        )

    return app


def create_production_app() -> FastAPI:
    """Entry point for ``uvicorn --factory backend.interfaces.http.app:create_production_app``."""
    settings = Settings()
    configure_logging(settings.log_level)
    return create_app(build_container(settings), owns_container=True)
