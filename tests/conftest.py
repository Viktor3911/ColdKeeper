"""Shared fixtures: controlled clock, fast hasher, migrated test database, app client and helpers."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.adapters.security.passwords import ScryptParameters, ScryptPasswordHasher
from backend.composition import Container, build_container
from backend.domain.organizations import Role
from backend.interfaces.http.app import create_app
from backend.settings import Environment, Settings

ROOT = Path(__file__).resolve().parent.parent
TEST_DATABASE_VARIABLE = "COLDKEEPER_TEST_DATABASE_URL"
START = datetime(2026, 11, 3, 0, 0, tzinfo=UTC)
PASSWORD = "correct horse battery"


class FakeClock:
    """Manually advanced time; no sleeping in tests."""

    def __init__(self, moment: datetime = START) -> None:
        self.moment = moment

    def now(self) -> datetime:
        """Current fake time."""
        return self.moment

    def advance(self, delta: timedelta) -> datetime:
        """Move forward and return the new time."""
        self.moment += delta
        return self.moment


def fast_hasher() -> ScryptPasswordHasher:
    """Tiny work factors: tests check behaviour, not cost."""
    return ScryptPasswordHasher(ScryptParameters(n=2**4, r=8, p=1))


@pytest.fixture(scope="session")
def database_url() -> str:
    """The test database is required: tests that need it fail loudly instead of being skipped."""
    url = os.environ.get(TEST_DATABASE_VARIABLE)
    if not url:
        pytest.fail(f"{TEST_DATABASE_VARIABLE} не задан. Запустите тесты через `task test` (поднимет тестовую БД).")
    return url


def _alembic(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session")
def migrated(database_url: str) -> str:
    """Clean schema from the migrations (not from metadata), once per run."""
    config = _alembic(database_url)
    # env.py calls asyncio.run(): run it outside the test event loop.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(command.downgrade, config, "base").result()
        pool.submit(command.upgrade, config, "head").result()
    return database_url


async def _truncate(url: str) -> None:
    engine = create_async_engine(url)
    async with engine.begin() as connection:
        tables = (
            await connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'alembic_version'"),
            )
        ).scalars()
        names = ", ".join(f'"{name}"' for name in tables)
        if names:
            await connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    await engine.dispose()


@pytest.fixture
def clock() -> FakeClock:
    """Fresh fake clock per test."""
    return FakeClock()


@pytest.fixture
def settings(migrated: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings for the test database; a developer's COLDKEEPER_* variables (e.g. a bot token) are ignored."""
    for name in list(os.environ):
        if name.startswith("COLDKEEPER_") and name != TEST_DATABASE_VARIABLE:
            monkeypatch.delenv(name)
    return Settings(
        env=Environment.TEST,
        database_url=SecretStr(migrated),
        allowed_origins=["http://testserver"],
        public_url="http://testserver",
        demo_dir=tmp_path / ".demo",
        _env_file=None,
    )


@pytest.fixture
async def container(settings: Settings, clock: FakeClock) -> AsyncIterator[Container]:
    """Production wiring with the fake clock and the fast hasher, on an empty database."""
    await _truncate(settings.database_url.get_secret_value())
    built = build_container(settings, clock=clock, hasher=fast_hasher())
    yield built
    await built.close()


@pytest.fixture
async def client(container: Container) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP client against the ASGI app (no network)."""
    app = create_app(container)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@dataclass
class Session:
    """A signed-in browser: cookie in the client, CSRF token for changes."""

    client: httpx.AsyncClient
    csrf: str

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Read."""
        return await self.client.get(url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Change with CSRF."""
        return await self.client.post(url, headers={"X-CSRF-Token": self.csrf}, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Change with CSRF."""
        return await self.client.put(url, headers={"X-CSRF-Token": self.csrf}, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Delete with CSRF."""
        return await self.client.delete(url, headers={"X-CSRF-Token": self.csrf}, **kwargs)


async def make_user(container: Container, organization: str, login: str, role: Role = Role.OWNER) -> None:
    """Organization (if missing) and a user."""
    if await container.admin.get_organization(organization) is None:
        await container.admin.create_organization(organization)
    await container.admin.create_user(organization, login, PASSWORD, role)


async def sign_in(container: Container, login: str) -> Session:
    """A separate client signed in as ``login``."""
    app = create_app(container)
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")
    response = await http.post("/api/v1/auth/login", json={"login": login, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return Session(http, response.json()["csrf_token"])


@dataclass
class Fixture:
    """A site → room → equipment → point with a registered and assigned sensor."""

    session: Session
    site_id: str
    room_id: str
    equipment_id: str
    point_id: str
    sensor_id: str
    hardware_id: str
    token: str


async def build_point(
    session: Session,
    *,
    hardware_id: str = "utx-test01",
    kind: str = "physical",
    low: float = 2.0,
    high: float = 6.0,
    assign_from: datetime | None = None,
) -> Fixture:
    """Create a full chain through the API like the owner would."""
    site = (await session.post("/api/v1/sites", json={"name": "Кафе", "timezone": "Asia/Vladivostok"})).json()
    room = (await session.post("/api/v1/rooms", json={"site_id": site["id"], "name": "Кухня"})).json()
    equipment = (
        await session.post("/api/v1/equipment", json={"room_id": room["id"], "name": "Шкаф №1", "kind": "refrigerator"})
    ).json()
    point = (
        await session.post(
            "/api/v1/points",
            json={
                "equipment_id": equipment["id"],
                "name": "Камера",
                "settings": {"low_threshold": low, "high_threshold": high},
            },
        )
    ).json()
    sensor = (await session.post("/api/v1/sensors", json={"hardware_id": hardware_id, "kind": kind})).json()
    body: dict[str, Any] = {"point_id": point["id"]}
    if assign_from is not None:
        body["starts_at"] = assign_from.isoformat()
    assigned = await session.post(f"/api/v1/sensors/{sensor['sensor_id']}/assignment", json=body)
    assert assigned.status_code == 201, assigned.text
    return Fixture(
        session=session,
        site_id=site["id"],
        room_id=room["id"],
        equipment_id=equipment["id"],
        point_id=point["id"],
        sensor_id=sensor["sensor_id"],
        hardware_id=hardware_id,
        token=sensor["token"],
    )


async def push(
    client: httpx.AsyncClient,
    token: str,
    hardware_id: str,
    moment: datetime,
    temperature: float | None,
    *,
    ok: bool = True,
) -> httpx.Response:
    """Send one UnitX reading."""
    body = {"id": hardware_id, "ts": int(moment.timestamp()), "t": temperature, "ok": ok}
    return await client.post("/api/v1/ingest/unitx", params={"token": token}, json=body)
