"""Organizations never see or change each other's data, whatever ids are put into URLs or bodies."""

from __future__ import annotations

from datetime import date, timedelta

from backend.composition import Container
from tests.conftest import FakeClock, build_point, make_user, push, sign_in


async def test_foreign_ids_are_not_found(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе", "alice")
    await make_user(container, "Магазин", "bob")
    alice = await sign_in(container, "alice")
    bob = await sign_in(container, "bob")
    point = await build_point(alice)
    await push(alice.client, point.token, point.hardware_id, clock.now(), 4.0)

    day = date(2026, 11, 3).isoformat()
    period = {
        "start": (clock.now() - timedelta(days=1)).isoformat(),
        "end": (clock.now() + timedelta(days=1)).isoformat(),
    }
    reads = [
        await bob.get(f"/api/v1/equipment/{point.equipment_id}"),
        await bob.get(f"/api/v1/points/{point.point_id}/series", params=period),
        await bob.get(f"/api/v1/sensors/{point.sensor_id}"),
        await bob.get("/api/v1/journal/daily", params={"first": day, "last": day, "site_id": point.site_id}),
        await bob.get(
            "/api/v1/journal/raw/export", params={"first": day, "last": day, "equipment_id": point.equipment_id}
        ),
    ]
    assert [response.status_code for response in reads] == [404] * len(reads)

    writes = [
        await bob.put(f"/api/v1/sites/{point.site_id}", json={"name": "Захват"}),
        await bob.post("/api/v1/rooms", json={"site_id": point.site_id, "name": "Чужая"}),
        await bob.delete(f"/api/v1/points/{point.point_id}"),
        await bob.post(f"/api/v1/sensors/{point.sensor_id}/token"),
        await bob.post(f"/api/v1/sensors/{point.sensor_id}/assignment", json={"point_id": point.point_id}),
    ]
    assert [response.status_code for response in writes] == [404] * len(writes)


async def test_lists_contain_only_own_data(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе", "alice")
    await make_user(container, "Магазин", "bob")
    alice = await sign_in(container, "alice")
    bob = await sign_in(container, "bob")
    point = await build_point(alice)
    await push(alice.client, point.token, point.hardware_id, clock.now(), 4.0)

    assert (await bob.get("/api/v1/overview")).json() == []
    assert (await bob.get("/api/v1/sensors")).json() == []
    assert (await bob.get("/api/v1/incidents")).json() == []
    assert (await bob.get("/api/v1/recipients")).json()["recipients"] == []
    inventory = (await bob.get("/api/v1/inventory")).json()
    assert inventory == {"sites": [], "rooms": [], "equipment": [], "points": []}
    day = date(2026, 11, 3).isoformat()
    journal = (await bob.get("/api/v1/journal/daily", params={"first": day, "last": day})).json()
    assert journal["rows"] == []


async def test_sensor_of_another_organization_cannot_be_registered_twice(container: Container) -> None:
    await make_user(container, "Кафе", "alice")
    await make_user(container, "Магазин", "bob")
    alice = await sign_in(container, "alice")
    bob = await sign_in(container, "bob")
    assert (await alice.post("/api/v1/sensors", json={"hardware_id": "utx-shared"})).status_code == 201
    assert (await bob.post("/api/v1/sensors", json={"hardware_id": "utx-shared"})).status_code == 409
