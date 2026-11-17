"""UnitX ingest: authentication, validation, idempotency, probe failures, late and unassigned readings."""

from __future__ import annotations

from datetime import timedelta

import httpx
from sqlalchemy import func, select

from backend.adapters.db.models import MeasurementRow
from backend.composition import Container
from tests.conftest import FakeClock, build_point, make_user, push, sign_in


async def _count(container: Container) -> int:
    async with container.engine.connect() as connection:
        return int((await connection.execute(select(func.count()).select_from(MeasurementRow))).scalar_one())


async def _owner_point(container: Container) -> tuple[httpx.AsyncClient, str, str, str]:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    point = await build_point(session)
    return session.client, point.token, point.hardware_id, point.point_id


async def test_valid_reading_is_stored_and_shown(container: Container, clock: FakeClock) -> None:
    client, token, hardware_id, point_id = await _owner_point(container)
    response = await push(client, token, hardware_id, clock.now(), 4.2)
    assert response.status_code == 204
    overview = (await client.get("/api/v1/overview")).json()
    assert overview[0]["last_temperature"] == 4.2
    assert overview[0]["status"] == "normal"
    series = await client.get(
        f"/api/v1/points/{point_id}/series",
        params={
            "start": (clock.now() - timedelta(hours=1)).isoformat(),
            "end": (clock.now() + timedelta(hours=1)).isoformat(),
        },
    )
    assert [item["value"] for item in series.json()] == [4.2]


async def test_wrong_token_or_hardware_id_is_rejected(container: Container, clock: FakeClock) -> None:
    client, token, hardware_id, _ = await _owner_point(container)
    assert (await push(client, "x" * 43, hardware_id, clock.now(), 4.0)).status_code == 401
    assert (await push(client, token, "utx-other", clock.now(), 4.0)).status_code == 403
    assert await _count(container) == 0


async def test_identical_repeat_is_accepted_without_a_duplicate(container: Container, clock: FakeClock) -> None:
    client, token, hardware_id, _ = await _owner_point(container)
    assert (await push(client, token, hardware_id, clock.now(), 4.0)).status_code == 204
    assert (await push(client, token, hardware_id, clock.now(), 4.0)).status_code == 204
    assert await _count(container) == 1


async def test_conflicting_value_does_not_overwrite_history(container: Container, clock: FakeClock) -> None:
    client, token, hardware_id, point_id = await _owner_point(container)
    await push(client, token, hardware_id, clock.now(), 4.0)
    conflict = await push(client, token, hardware_id, clock.now(), 9.0)
    assert conflict.status_code == 409
    overview = (await client.get("/api/v1/overview")).json()
    assert overview[0]["last_temperature"] == 4.0
    assert point_id


async def test_probe_failure_is_stored_as_an_error_not_as_zero(container: Container, clock: FakeClock) -> None:
    client, token, hardware_id, _ = await _owner_point(container)
    assert (await push(client, token, hardware_id, clock.now(), None, ok=False)).status_code == 204
    point = (await client.get("/api/v1/overview")).json()[0]
    assert point["status"] == "sensor_error"
    assert point["last_temperature"] is None


async def test_invalid_requests(container: Container, clock: FakeClock) -> None:
    client, token, hardware_id, _ = await _owner_point(container)
    url = "/api/v1/ingest/unitx"
    not_json = await client.post(url, params={"token": token}, content=b"{not json")
    assert not_json.status_code == 400
    missing_t = await client.post(
        url,
        params={"token": token},
        json={"id": hardware_id, "ts": int(clock.now().timestamp()), "ok": True},
    )
    assert missing_t.status_code == 422
    too_big = await client.post(url, params={"token": token}, content=b" " * 5000)
    assert too_big.status_code == 413
    future = await push(client, token, hardware_id, clock.now() + timedelta(hours=1), 4.0)
    assert future.status_code == 422
    assert await _count(container) == 0


async def test_validation_errors_never_echo_the_token(container: Container) -> None:
    client, _, _, _ = await _owner_point(container)
    response = await client.post("/api/v1/ingest/unitx", params={"token": "short-secret"}, json={})
    assert response.status_code == 422
    assert "short-secret" not in response.text


async def test_late_reading_is_history_and_does_not_roll_back_the_status(
    container: Container, clock: FakeClock
) -> None:
    client, token, hardware_id, _ = await _owner_point(container)
    await push(client, token, hardware_id, clock.now(), 4.0)
    late = await push(client, token, hardware_id, clock.now() - timedelta(minutes=30), 12.0)
    assert late.status_code == 204
    point = (await client.get("/api/v1/overview")).json()[0]
    assert point["last_temperature"] == 4.0
    assert point["status"] == "normal"
    assert await _count(container) == 2


async def test_reading_without_assignment_stays_with_the_sensor(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    registered = (await session.post("/api/v1/sensors", json={"hardware_id": "utx-spare"})).json()
    assert (await push(session.client, registered["token"], "utx-spare", clock.now(), 5.5)).status_code == 204
    sensors = (await session.get("/api/v1/sensors")).json()
    assert sensors[0]["last_temperature"] == 5.5
    assert sensors[0]["last_unassigned"] is True
    assert sensors[0]["point"] is None


async def test_revoked_or_reissued_token_stops_working(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    point = await build_point(session)
    new = (await session.post(f"/api/v1/sensors/{point.sensor_id}/token")).json()
    assert (await push(session.client, point.token, point.hardware_id, clock.now(), 4.0)).status_code == 401
    assert (await push(session.client, new["token"], point.hardware_id, clock.now(), 4.0)).status_code == 204
    assert (await session.delete(f"/api/v1/sensors/{point.sensor_id}/token")).status_code == 204
    clock.advance(timedelta(minutes=1))
    assert (await push(session.client, new["token"], point.hardware_id, clock.now(), 4.0)).status_code == 401
