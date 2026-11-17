"""From ingest to the exported journal, sensor replacement and the switch from simulation to a device."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

from docx import Document
from openpyxl import load_workbook

from backend.composition import Container
from tests.conftest import FakeClock, build_point, make_user, push, sign_in

# 2026-11-03 10:00 in Vladivostok (UTC+10) is 00:00 UTC.
DAY1_CONTROL = datetime(2026, 11, 3, 0, 0, tzinfo=UTC)


async def test_ingest_to_daily_journal_and_exports(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе «Север»", "owner")
    session = await sign_in(container, "owner")
    clock.moment = DAY1_CONTROL - timedelta(hours=2)
    point = await build_point(session, kind="simulated", assign_from=clock.now())
    # Day 1: readings every 10 minutes from 08:00 to 12:00 local time, one probe failure at 10:00.
    moment = clock.now()
    while moment < DAY1_CONTROL + timedelta(hours=2):
        clock.moment = moment + timedelta(seconds=5)
        ok = moment != DAY1_CONTROL
        response = await push(
            session.client, point.token, point.hardware_id, moment, 4.0 + (moment.minute / 100), ok=ok
        )
        assert response.status_code == 204, response.text
        moment += timedelta(minutes=10)
    # Day 2 has no data at all; the journal is requested later.
    clock.moment = DAY1_CONTROL + timedelta(days=2)

    params = {"first": "2026-11-03", "last": "2026-11-04", "equipment_id": point.equipment_id}
    journal = (await session.get("/api/v1/journal/daily", params=params)).json()
    assert journal["has_simulation"] is True
    day1, day2 = journal["rows"]
    assert day1["day"] == "2026-11-03"
    assert day1["control_state"] == "ok"
    # 10:00 failed, the next valid reading in the 30-minute window is 10:10 local time.
    assert day1["control_measured_at"].startswith("2026-11-03T00:10:00")
    assert day1["control_temperature"] == 4.1
    assert day1["error_count"] == 1
    assert day1["sources"] == ["simulator"]
    assert day2["day"] == "2026-11-04"
    assert day2["control_state"] == "no_data"
    assert day2["control_temperature"] is None
    assert day2["valid_count"] == 0

    csv_response = await session.get("/api/v1/journal/daily/export", params={**params, "format": "csv"})
    assert csv_response.status_code == 200
    disposition = unquote(csv_response.headers["content-disposition"])
    assert disposition.endswith("journal_2026-11-03_2026-11-04_demo.csv")
    rows = list(csv.reader(io.StringIO(csv_response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[1][:6] == ["Кафе «Север»", "Кафе", "Кухня", "Шкаф №1", "Камера", "03.11.2026"]
    assert rows[1][6] == "10:10"
    assert rows[1][7] == "4,1"
    assert rows[2][8] == "нет данных"
    assert rows[1][-1] == "симуляция"

    xlsx = await session.get("/api/v1/journal/daily/export", params={**params, "format": "xlsx"})
    sheet = load_workbook(io.BytesIO(xlsx.content)).active
    assert sheet is not None
    assert sheet.cell(row=3, column=9).value == "нет данных"

    form = await session.get("/api/v1/journal/form/export", params=params)
    assert form.status_code == 200
    assert form.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml")
    assert unquote(form.headers["content-disposition"]).endswith("journal_sanpin_2026-11-03_2026-11-04_demo.docx")
    (page,) = Document(io.BytesIO(form.content)).tables  # one site, one month
    assert page.cell(2, 1).text == "Шкаф №1"
    assert [page.cell(2, 1 + day).text for day in (3, 4)] == ["4,1", "—"]

    raw = await session.get("/api/v1/journal/raw/export", params={**params, "format": "csv"})
    raw_rows = list(csv.reader(io.StringIO(raw.content.decode("utf-8-sig")), delimiter=";"))
    assert len(raw_rows) == 1 + 24  # header + every stored measurement
    assert any(row[10] == "ошибка датчика" and row[9] == "" for row in raw_rows[1:])


async def test_sensor_replacement_keeps_history_at_the_point(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    old = await build_point(session, hardware_id="demo-old", kind="simulated")
    for _ in range(3):
        clock.advance(timedelta(minutes=1))
        assert (await push(session.client, old.token, old.hardware_id, clock.now(), 4.0)).status_code == 204

    # Switch: a real device with a new id and token takes over the point from now on.
    clock.advance(timedelta(minutes=1))
    real = (await session.post("/api/v1/sensors", json={"hardware_id": "utx-real01", "kind": "physical"})).json()
    switched = await session.post(f"/api/v1/sensors/{real['sensor_id']}/assignment", json={"point_id": old.point_id})
    assert switched.status_code == 201
    for _ in range(2):
        clock.advance(timedelta(minutes=1))
        assert (await push(session.client, real["token"], "utx-real01", clock.now(), 5.0)).status_code == 204

    # The simulator keeps sending under its own key: stored for the sensor, not for the point.
    assert (await push(session.client, old.token, old.hardware_id, clock.now(), 9.9)).status_code == 204

    period = {
        "start": (clock.now() - timedelta(hours=1)).isoformat(),
        "end": (clock.now() + timedelta(minutes=1)).isoformat(),
    }
    series = (await session.get(f"/api/v1/points/{old.point_id}/series", params=period)).json()
    assert [(item["value"], item["source"]) for item in series] == [
        (4.0, "simulator"),
        (4.0, "simulator"),
        (4.0, "simulator"),
        (5.0, "device"),
        (5.0, "device"),
    ]
    sensors = {item["hardware_id"]: item for item in (await session.get("/api/v1/sensors")).json()}
    assert sensors["demo-old"]["assignment"] is None
    assert sensors["demo-old"]["last_unassigned"] is True
    assert sensors["utx-real01"]["point"]["point_id"] == old.point_id
    detail = (await session.get(f"/api/v1/sensors/{old.sensor_id}")).json()
    assert detail["history"][0]["ends_at"] is not None


async def test_assignment_cannot_rewrite_stored_history(container: Container, clock: FakeClock) -> None:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    point = await build_point(session)
    clock.advance(timedelta(minutes=5))
    await push(session.client, point.token, point.hardware_id, clock.now(), 4.0)
    other = (await session.post("/api/v1/sensors", json={"hardware_id": "utx-other"})).json()
    backdated = await session.post(
        f"/api/v1/sensors/{other['sensor_id']}/assignment",
        json={"point_id": point.point_id, "starts_at": (clock.now() - timedelta(minutes=10)).isoformat()},
    )
    assert backdated.status_code == 409
    assert (await session.delete(f"/api/v1/points/{point.point_id}")).status_code == 409
