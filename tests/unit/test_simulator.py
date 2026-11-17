"""Reproducible generation and scenarios, checked against the real monitoring rules (no HTTP)."""

from __future__ import annotations

import itertools
import time
import uuid
from datetime import UTC, datetime, timedelta

from backend.domain.equipment import PointSettings
from backend.domain.monitoring import IncidentClosed, IncidentOpened, IncidentType, PointState, apply_reading
from backend.simulator.devices import Device, DeviceFile
from backend.simulator.generator import Sample, derive_seed, generate
from backend.simulator.model import PROFILES
from backend.simulator.runner import Report, run_live_device, send_history
from backend.simulator.scenarios import SCENARIOS, EventKind, build_timeline
from backend.simulator.transport import Outcome, SendResult

START = datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
STEP = timedelta(minutes=1)
DEMO = PointSettings(
    low_threshold=2.0,
    high_threshold=6.0,
    deviation_duration=timedelta(minutes=3),
    recovery_duration=timedelta(minutes=2),
    offline_timeout=timedelta(minutes=3),
)


def _series(scenario: str, minutes: int, *, seed: int = 7, profile: str = "refrigerator") -> list[Sample]:
    end = START + timedelta(minutes=minutes)
    timeline = build_timeline([(SCENARIOS[scenario], START, START, end)])
    return list(
        generate(PROFILES[profile], timeline, seed=seed, start=START, step=STEP, duration=end - START),
    )


def _evaluate(samples: list[Sample], settings: PointSettings = DEMO) -> list[IncidentOpened | IncidentClosed]:
    state = PointState(point_id=uuid.uuid4())
    transitions: list[IncidentOpened | IncidentClosed] = []
    for sample in samples:
        if not sample.delivered:
            continue
        result = apply_reading(
            state,
            settings,
            measured_at=sample.measured_at,
            received_at=sample.measured_at,
            temperature=sample.temperature,
            sensor_ok=sample.ok,
        )
        state = result.state
        transitions.extend(result.transitions)
    return transitions


def test_same_inputs_give_the_same_series() -> None:
    assert _series("door_spikes", 240) == _series("door_spikes", 240)
    assert _series("door_spikes", 240, seed=8) != _series("door_spikes", 240)


def test_device_streams_are_independent_and_stable() -> None:
    assert derive_seed(1, "demo-fridge-1") == derive_seed(1, "demo-fridge-1")
    assert derive_seed(1, "demo-fridge-1") != derive_seed(1, "demo-fridge-2")


def test_normal_operation_is_a_smooth_cycle_inside_the_range() -> None:
    values = [sample.temperature for sample in _series("normal", 24 * 60) if sample.temperature is not None]
    assert min(values) > 2.0 and max(values) < 6.0
    steps = [abs(after - before) for before, after in itertools.pairwise(values)]
    assert max(steps) < 1.0  # no independent random jumps between points


def test_door_spikes_are_visible_but_never_confirmed() -> None:
    samples = _series("door_spikes", 6 * 60)
    assert max(sample.temperature or 0 for sample in samples) > 6.0
    assert not any(item.type is IncidentType.TEMPERATURE for item in _evaluate(samples))


def test_sustained_excursion_opens_one_alarm_and_recovers() -> None:
    samples = _series("sustained_excursion", 70)
    transitions = [item for item in _evaluate(samples) if item.type is IncidentType.TEMPERATURE]
    assert [type(item) for item in transitions] == [IncidentOpened, IncidentClosed]


def test_door_left_open_alarms_within_minutes_and_recovers() -> None:
    samples = _series("door_left_open", 30)
    transitions = [item for item in _evaluate(samples) if item.type is IncidentType.TEMPERATURE]
    assert [type(item) for item in transitions] == [IncidentOpened, IncidentClosed]
    assert transitions[0].at - START <= timedelta(minutes=6)  # a live demo alarm, not a 15-minute wait
    assert transitions[1].at - START <= timedelta(minutes=20)


def test_freezer_excursion_too() -> None:
    samples = _series("sustained_excursion", 70, profile="freezer")
    settings = PointSettings(
        low_threshold=-22.0,
        high_threshold=-16.0,
        deviation_duration=timedelta(minutes=3),
        recovery_duration=timedelta(minutes=2),
    )
    transitions = [item for item in _evaluate(samples, settings) if item.type is IncidentType.TEMPERATURE]
    assert [type(item) for item in transitions] == [IncidentOpened, IncidentClosed]


def test_probe_failure_sends_ok_false_without_temperature() -> None:
    failed = [sample for sample in _series("probe_failure", 20) if not sample.ok]
    assert len(failed) == 4
    assert all(sample.temperature is None and sample.delivered for sample in failed)


def test_connection_loss_stops_sending() -> None:
    lost = [sample for sample in _series("connection_loss", 20) if not sample.delivered]
    assert len(lost) == 8


def _file(history_end: datetime) -> DeviceFile:
    device = Device(
        hardware_id="demo-fridge-1",
        token="x" * 32,
        profile="refrigerator",
        history_scenario="routine_week",
        live_scenario="door_spikes",
    )
    return DeviceFile(seed=1, history_start=START, history_end=history_end, devices=[device])


async def test_history_never_sends_the_future() -> None:
    history_end = START + timedelta(hours=3)
    sent: list[Sample] = []

    async def send(_hardware_id: str, _token: str, sample: Sample) -> SendResult:
        sent.append(sample)
        return SendResult(Outcome.ACCEPTED, 204)

    report = await send_history(_file(history_end), send, concurrency=4)
    assert len(sent) == 180
    assert max(sample.measured_at for sample in sent) < history_end
    assert report.outcomes[Outcome.ACCEPTED] == 180


async def test_live_waits_for_real_time_and_continues_the_same_series() -> None:
    history_end = START + timedelta(hours=1)
    file = _file(history_end)
    now = [history_end + timedelta(minutes=5)]
    sent: list[Sample] = []

    async def sleep(seconds: float) -> None:
        now[0] += timedelta(seconds=seconds)

    async def send(_hardware_id: str, _token: str, sample: Sample) -> SendResult:
        assert sample.measured_at <= now[0]  # never ahead of the clock
        sent.append(sample)
        return SendResult(Outcome.ACCEPTED, 204)

    launch = now[0]
    await run_live_device(
        file.devices[0],
        file,
        send,
        clock=lambda: now[0],
        sleep=sleep,
        launch=launch,
        until=launch + timedelta(minutes=30),
        report=Report(),
    )
    assert sent[0].measured_at == launch
    assert len(sent) == 30


async def test_live_fast_forward_over_a_week_is_quick() -> None:
    file = _file(START + timedelta(days=7))
    launch = file.history_end + timedelta(minutes=3)
    now = [launch]
    sent: list[Sample] = []

    async def sleep(seconds: float) -> None:
        now[0] += timedelta(seconds=seconds)

    async def send(_hardware_id: str, _token: str, sample: Sample) -> SendResult:
        sent.append(sample)
        return SendResult(Outcome.ACCEPTED, 204)

    started = time.perf_counter()
    await run_live_device(
        file.devices[0],
        file,
        send,
        clock=lambda: now[0],
        sleep=sleep,
        launch=launch,
        until=launch + timedelta(minutes=10),
    )
    assert len(sent) == 10
    assert time.perf_counter() - started < 5  # a week of fast-forward must not block the live stream


def test_repeating_events_are_computed_not_listed() -> None:
    end = START + timedelta(days=3650)
    timeline = build_timeline([(SCENARIOS["door_spikes"], START, START, end)])
    assert len(timeline.events) == 1
    assert timeline.active(EventKind.DOOR_OPEN, START + timedelta(days=3000, minutes=4))
    assert not timeline.active(EventKind.DOOR_OPEN, START + timedelta(days=3000, minutes=6))
