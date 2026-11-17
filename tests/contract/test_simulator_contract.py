"""The simulator and a UnitX-compatible sender go through the same public ingest and use case."""

from __future__ import annotations

import json
from datetime import timedelta

import httpx

from backend.adapters.unitx.payload import UnitXPayload, to_reading
from backend.composition import Container
from backend.interfaces.cli.demo import DemoSeeder
from backend.interfaces.http.app import create_app
from backend.simulator import devices as device_files
from backend.simulator.generator import Sample
from backend.simulator.runner import send_history
from backend.simulator.transport import Outcome, UnitXTransport, unitx_body
from tests.conftest import FakeClock


def test_simulator_body_is_the_documented_unitx_format() -> None:
    sample = Sample(measured_at=FakeClock().now(), temperature=-18.3, ok=True, delivered=True)
    body = unitx_body("demo-chest-1", sample)
    assert set(body) == {"id", "ts", "t", "ok"}
    reading = to_reading(UnitXPayload.model_validate_json(json.dumps(body)))
    assert reading.temperature == -18.3
    assert reading.measured_at == sample.measured_at


async def test_demo_seed_history_through_ingest_and_rerun_without_duplicates(
    container: Container, clock: FakeClock
) -> None:
    seeder = DemoSeeder(container, container.settings.demo_dir)
    lines = await seeder.run()
    assert any("devices.json" in line for line in lines)
    file = device_files.load(container.settings.demo_dir / "devices.json")
    assert len(file.devices) == 5
    assert file.history_end - file.history_start == timedelta(days=7)

    # Only the last two hours of history to keep the test fast; the real command sends 7 days.
    short = file.model_copy(update={"history_start": file.history_end - timedelta(hours=2)})
    app = create_app(container)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        transport = UnitXTransport(client, "http://testserver")
        report = await send_history(short, transport.send, concurrency=4)
        assert report.outcomes[Outcome.ACCEPTED] > 0
        assert report.outcomes[Outcome.REJECTED] == 0
        assert report.outcomes[Outcome.CONFLICT] == 0
        again = await send_history(short, transport.send, concurrency=4)  # identical values: idempotent
        assert again.outcomes[Outcome.CONFLICT] == 0

    # A second seed run creates no duplicates and keeps anchors and working keys (a running simulator survives).
    await DemoSeeder(container, container.settings.demo_dir).run()
    rerun = device_files.load(container.settings.demo_dir / "devices.json")
    assert [device.token for device in rerun.devices] == [device.token for device in file.devices]
    assert (rerun.history_start, rerun.history_end) == (file.history_start, file.history_end)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        resent = await send_history(
            rerun.model_copy(update={"history_start": rerun.history_end - timedelta(hours=2)}),
            UnitXTransport(client, "http://testserver").send,
            concurrency=4,
        )
    assert resent.outcomes[Outcome.CONFLICT] == 0
    assert resent.outcomes[Outcome.REJECTED] == 0
    credentials = json.loads((container.settings.demo_dir / "credentials.json").read_text(encoding="utf-8"))
    assert set(credentials) == {"demo-owner", "demo-observer", "demo-shop"}
    assert clock.now() == file.history_end
