"""Incidents through the real ingest and worker steps, on controlled time."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import insert, select

from backend.adapters.db.models import RecipientRow
from backend.adapters.telegram.senders import DryRunSender
from backend.application.ports import DeliveryError
from backend.composition import Container, build_container, build_delivery
from backend.domain.incidents import DeliveryStatus
from tests.conftest import FakeClock, Fixture, build_point, fast_hasher, make_user, push, sign_in

MINUTE = timedelta(minutes=1)


async def _setup(container: Container) -> Fixture:
    await make_user(container, "Кафе", "owner")
    session = await sign_in(container, "owner")
    return await build_point(session)


async def _feed(point: Fixture, clock: FakeClock, values: Sequence[float | None]) -> None:
    for value in values:
        clock.advance(MINUTE)
        response = await push(
            point.session.client, point.token, point.hardware_id, clock.now(), value, ok=value is not None
        )
        assert response.status_code == 204, response.text


async def _incidents(point: Fixture) -> list[dict[str, object]]:
    response = await point.session.get("/api/v1/incidents")
    return list(response.json())


async def test_short_spike_creates_no_incident(container: Container, clock: FakeClock) -> None:
    point = await _setup(container)
    await _feed(point, clock, [4.0, 9.0, 9.5, 4.0, 4.1])
    assert await _incidents(point) == []


async def test_sustained_deviation_one_incident_then_recovery(container: Container, clock: FakeClock) -> None:
    point = await _setup(container)
    await _feed(point, clock, [4.0] + [9.0] * 10)
    incidents = await _incidents(point)
    assert len(incidents) == 1
    assert incidents[0]["type"] == "temperature"
    assert incidents[0]["closed_at"] is None
    events = incidents[0]["events"]
    assert isinstance(events, list)
    assert events[0]["kind"] == "opened"
    assert events[0]["deliveries"] == []  # stored even without recipients
    assert "Шкаф №1" in events[0]["text"]

    await _feed(point, clock, [4.0, 4.0, 4.0])
    incidents = await _incidents(point)
    assert len(incidents) == 1
    assert incidents[0]["closed_at"] is not None


async def test_connection_loss_is_detected_without_requests(container: Container, clock: FakeClock) -> None:
    point = await _setup(container)
    await _feed(point, clock, [4.0])
    clock.advance(timedelta(minutes=6))
    assert await container.check_connectivity() == 1
    assert await container.check_connectivity() == 0  # a restarted or repeated worker adds nothing
    overview = (await point.session.get("/api/v1/overview")).json()
    assert overview[0]["status"] == "offline"
    await _feed(point, clock, [4.0])
    incidents = await _incidents(point)
    assert [(item["type"], item["closed_at"] is not None) for item in incidents] == [("connection_lost", True)]


async def test_worker_restart_does_not_duplicate_incidents(container: Container, clock: FakeClock) -> None:
    point = await _setup(container)
    await _feed(point, clock, [4.0])
    clock.advance(timedelta(minutes=10))
    await container.check_connectivity()
    restarted = build_container(container.settings, clock=clock, hasher=fast_hasher())
    try:
        assert await restarted.check_connectivity() == 0
    finally:
        await restarted.close()
    assert len(await _incidents(point)) == 1


class FlakySender:
    """Fails twice, then succeeds."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def is_dry_run(self) -> bool:
        return False

    async def send(self, chat_id: int, text: str) -> None:
        self.calls += 1
        if self.calls <= 2:
            raise DeliveryError("сеть недоступна")
        assert chat_id == 42 and text


async def _with_recipient(container: Container) -> None:
    """A bound chat, as if the binding code had been sent to the bot."""
    organization = await container.admin.get_organization("Кафе")
    assert organization is not None
    async with container.engine.begin() as connection:
        await connection.execute(
            insert(RecipientRow).values(
                id=uuid4(),
                organization_id=organization.id,
                chat_id=42,
                title="Шеф",
                is_active=True,
                created_at=container.clock.now(),
            ),
        )


async def test_delivery_is_retried_with_backoff_and_then_sent(container: Container, clock: FakeClock) -> None:
    point = await _setup(container)
    await _with_recipient(container)
    await _feed(point, clock, [4.0] + [9.0] * 6)
    sender = FlakySender()
    deliver = build_delivery(container, sender)
    assert await deliver() == 1  # first attempt fails, next one is scheduled later
    assert await deliver() == 0  # not due yet
    clock.advance(timedelta(seconds=31))
    assert await deliver() == 1
    clock.advance(timedelta(minutes=1, seconds=1))
    assert await deliver() == 1
    delivery = (await _incidents(point))[0]["events"][0]["deliveries"][0]  # type: ignore[index]
    assert delivery["status"] == DeliveryStatus.SENT.value
    assert delivery["attempts"] == 3


async def test_dry_run_records_without_sending(container: Container, clock: FakeClock) -> None:
    point = await _setup(container)
    await _with_recipient(container)
    await _feed(point, clock, [4.0] + [9.0] * 6)
    assert await build_delivery(container, DryRunSender())() == 1
    delivery = (await _incidents(point))[0]["events"][0]["deliveries"][0]  # type: ignore[index]
    assert delivery["status"] == "dry_run"


async def test_permanent_errors_fail_without_retries(container: Container, clock: FakeClock) -> None:
    class Blocked:
        @property
        def is_dry_run(self) -> bool:
            return False

        async def send(self, chat_id: int, text: str) -> None:
            raise DeliveryError("бот заблокирован", permanent=True)

    point = await _setup(container)
    await _with_recipient(container)
    await _feed(point, clock, [4.0] + [9.0] * 6)
    assert await build_delivery(container, Blocked())() == 1
    clock.advance(timedelta(hours=1))
    assert await build_delivery(container, Blocked())() == 0
    delivery = (await _incidents(point))[0]["events"][0]["deliveries"][0]  # type: ignore[index]
    assert delivery["status"] == "failed"
    assert delivery["last_error"] == "бот заблокирован"


async def test_binding_code_links_a_chat_once(container: Container, clock: FakeClock) -> None:
    point = await _setup(container)
    code = (await point.session.post("/api/v1/recipients/code")).json()["code"]
    reply = await container.recipients.confirm(code, 777, "Кухня")
    assert reply.startswith("Готово")
    assert (await container.recipients.confirm(code, 778, "Чужой")).startswith("Код не найден")
    recipients = (await point.session.get("/api/v1/recipients")).json()
    assert recipients["bot_configured"] is False
    assert [item["chat_id"] for item in recipients["recipients"]] == [777]
    async with container.engine.connect() as connection:
        assert len((await connection.execute(select(RecipientRow))).all()) == 1
    clock.advance(timedelta(minutes=20))
    expired = (await point.session.post("/api/v1/recipients/code")).json()["code"]
    clock.advance(timedelta(minutes=16))
    assert (await container.recipients.confirm(expired, 779, "Поздно")).startswith("Код не найден")
