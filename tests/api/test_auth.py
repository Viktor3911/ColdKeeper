"""Sign-in, sessions, CSRF, Origin and roles."""

from __future__ import annotations

from datetime import timedelta

import httpx

from backend.composition import Container
from backend.domain.organizations import Role
from tests.conftest import PASSWORD, FakeClock, make_user, sign_in


async def test_login_sets_an_http_only_cookie_and_session_works(
    container: Container, client: httpx.AsyncClient
) -> None:
    await make_user(container, "Кафе", "owner")
    response = await client.post("/api/v1/auth/login", json={"login": "Owner ", "password": PASSWORD})
    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "ck_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    session = await client.get("/api/v1/session")
    assert session.json()["login"] == "owner"
    assert session.json()["csrf_token"] == response.json()["csrf_token"]


async def test_wrong_password_and_unknown_login_look_the_same(container: Container, client: httpx.AsyncClient) -> None:
    await make_user(container, "Кафе", "owner")
    wrong = await client.post("/api/v1/auth/login", json={"login": "owner", "password": "wrong password"})
    unknown = await client.post("/api/v1/auth/login", json={"login": "nobody", "password": "wrong password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


async def test_repeated_failures_lock_the_login_for_a_while(
    container: Container,
    client: httpx.AsyncClient,
    clock: FakeClock,
) -> None:
    await make_user(container, "Кафе", "owner")
    for _ in range(5):
        await client.post("/api/v1/auth/login", json={"login": "owner", "password": "wrong password"})
    locked = await client.post("/api/v1/auth/login", json={"login": "owner", "password": PASSWORD})
    assert locked.status_code == 429
    assert int(locked.headers["retry-after"]) > 0
    clock.advance(timedelta(minutes=16))
    assert (await client.post("/api/v1/auth/login", json={"login": "owner", "password": PASSWORD})).status_code == 200


async def test_logout_revokes_the_session_on_the_server(container: Container) -> None:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    stolen_cookie = session.client.cookies.get("ck_session")
    assert (await session.post("/api/v1/auth/logout")).status_code == 204
    assert stolen_cookie is not None
    replay = await session.client.get("/api/v1/session", cookies={"ck_session": stolen_cookie})
    assert replay.status_code == 401


async def test_sessions_expire_after_inactivity(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    clock.advance(timedelta(days=8))
    assert (await session.get("/api/v1/session")).status_code == 401


async def test_changes_require_the_csrf_token_and_a_matching_origin(container: Container) -> None:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    no_token = await session.client.post("/api/v1/sites", json={"name": "Объект"})
    assert no_token.status_code == 403
    foreign = await session.client.post(
        "/api/v1/sites",
        json={"name": "Объект"},
        headers={"X-CSRF-Token": session.csrf, "Origin": "https://evil.example"},
    )
    assert foreign.status_code == 403
    assert (await session.post("/api/v1/sites", json={"name": "Объект"})).status_code == 201


async def test_observer_reads_but_cannot_change(container: Container) -> None:
    await make_user(container, "Кафе", "owner")
    await make_user(container, "Кафе", "viewer", Role.OBSERVER)
    owner = await sign_in(container, "owner")
    await owner.post("/api/v1/sites", json={"name": "Объект"})
    observer = await sign_in(container, "viewer")
    assert len((await observer.get("/api/v1/inventory")).json()["sites"]) == 1
    assert (await observer.post("/api/v1/sites", json={"name": "Другой"})).status_code == 403
    assert (await observer.post("/api/v1/sensors", json={"hardware_id": "utx-1"})).status_code == 403


async def test_anonymous_requests_are_rejected(client: httpx.AsyncClient) -> None:
    for url in ("/api/v1/overview", "/api/v1/inventory", "/api/v1/sensors", "/api/v1/recipients"):
        assert (await client.get(url)).status_code == 401
