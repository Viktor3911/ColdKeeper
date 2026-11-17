"""Incident rules on controlled time: no database, no sleeping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.domain.equipment import PointSettings
from backend.domain.monitoring import (
    Direction,
    IncidentClosed,
    IncidentOpened,
    IncidentType,
    PointState,
    PointStatus,
    Transition,
    apply_reading,
    apply_silence,
    is_live,
)

T0 = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
SETTINGS = PointSettings(low_threshold=2.0, high_threshold=6.0)  # 5 min deviation, 2 min recovery, 60 s, 5 min


class Point:
    """Feeds readings one minute apart and collects transitions."""

    def __init__(self, settings: PointSettings = SETTINGS) -> None:
        self.settings = settings
        self.state = PointState(point_id=uuid.uuid4())
        self.moment = T0
        self.transitions: list[Transition] = []

    def read(self, temperature: float | None, *, after: timedelta = MINUTE, ok: bool = True) -> PointState:
        self.moment += after
        result = apply_reading(
            self.state,
            self.settings,
            measured_at=self.moment,
            received_at=self.moment,
            temperature=temperature,
            sensor_ok=ok,
        )
        self.state = result.state
        self.transitions.extend(result.transitions)
        return self.state

    def silence(self, duration: timedelta) -> PointState:
        result = apply_silence(self.state, self.settings, self.moment + duration)
        self.state = result.state
        self.transitions.extend(result.transitions)
        return self.state

    def status(self) -> PointStatus:
        return self.state.status

    def opened(self, kind: IncidentType) -> list[IncidentOpened]:
        return [item for item in self.transitions if isinstance(item, IncidentOpened) and item.type is kind]

    def closed(self, kind: IncidentType) -> list[IncidentClosed]:
        return [item for item in self.transitions if isinstance(item, IncidentClosed) and item.type is kind]


def test_new_point_has_no_data_and_no_offline_incident() -> None:
    point = Point()
    assert point.status() is PointStatus.NO_DATA
    point.silence(timedelta(hours=5))
    assert point.status() is PointStatus.NO_DATA
    assert point.transitions == []


def test_short_spike_does_not_confirm_an_alarm() -> None:
    point = Point()
    point.read(4.0)
    point.read(8.5)
    assert point.status() is PointStatus.PENDING
    point.read(9.0)
    point.read(4.5)  # normal value resets the unconfirmed deviation
    assert point.status() is PointStatus.NORMAL
    assert point.opened(IncidentType.TEMPERATURE) == []


def test_sustained_deviation_opens_exactly_one_incident() -> None:
    point = Point()
    point.read(4.0)
    for _ in range(12):
        point.read(8.0)
    opened = point.opened(IncidentType.TEMPERATURE)
    assert len(opened) == 1
    assert opened[0].direction is Direction.HIGH
    assert opened[0].at == T0 + 7 * MINUTE  # first high reading at +2 min, confirmed 5 minutes later
    assert point.status() is PointStatus.ALARM


def test_low_temperature_is_a_deviation_too() -> None:
    point = Point()
    for _ in range(7):
        point.read(0.5)
    assert point.opened(IncidentType.TEMPERATURE)[0].direction is Direction.LOW


def test_recovery_needs_confirmed_normal_values() -> None:
    point = Point()
    for _ in range(7):
        point.read(9.0)
    assert point.status() is PointStatus.ALARM
    point.read(5.0)
    point.read(5.0)
    assert point.closed(IncidentType.TEMPERATURE) == []  # normal for 1 minute only
    point.read(6.5)  # bounce above the threshold breaks the recovery
    point.read(5.0)
    point.read(5.0)
    assert point.closed(IncidentType.TEMPERATURE) == []
    point.read(5.0)
    assert len(point.closed(IncidentType.TEMPERATURE)) == 1
    assert point.status() is PointStatus.NORMAL


def test_thresholds_themselves_are_allowed() -> None:
    point = Point()
    for _ in range(10):
        point.read(6.0)
    assert point.status() is PointStatus.NORMAL


def test_sensor_error_interrupts_confirmation_and_opens_its_own_incident() -> None:
    point = Point()
    point.read(8.0)
    point.read(8.0)
    point.read(8.0)
    point.read(None, ok=False)
    assert point.status() is PointStatus.SENSOR_ERROR
    assert len(point.opened(IncidentType.SENSOR_ERROR)) == 1
    point.read(8.0)
    point.read(8.0)
    point.read(8.0)
    assert point.opened(IncidentType.TEMPERATURE) == []  # counting restarted after the error
    assert len(point.closed(IncidentType.SENSOR_ERROR)) == 1


def test_gap_in_the_stream_restarts_the_deviation_series() -> None:
    point = Point()
    point.read(8.0)
    point.read(8.0)
    point.read(8.0, after=4 * MINUTE)  # more than 2.5 intervals without readings
    point.read(8.0)
    assert point.opened(IncidentType.TEMPERATURE) == []
    assert point.status() is PointStatus.PENDING


def test_silence_marks_offline_once_and_a_reading_restores_it() -> None:
    point = Point()
    point.read(4.0)
    point.silence(timedelta(minutes=4))
    assert point.status() is PointStatus.NORMAL
    point.silence(timedelta(minutes=6))
    point.silence(timedelta(minutes=9))  # the worker runs again: no duplicate
    assert len(point.opened(IncidentType.CONNECTION_LOST)) == 1
    assert point.status() is PointStatus.OFFLINE
    point.read(4.0, after=timedelta(minutes=10))
    assert len(point.closed(IncidentType.CONNECTION_LOST)) == 1
    assert point.status() is PointStatus.NORMAL


def test_missing_data_neither_confirms_nor_closes_an_alarm() -> None:
    point = Point()
    for _ in range(7):
        point.read(9.0)
    point.silence(timedelta(minutes=30))
    assert point.state.temperature_alarm is Direction.HIGH
    assert point.closed(IncidentType.TEMPERATURE) == []
    assert point.status() is PointStatus.OFFLINE


def test_pending_deviation_is_dropped_when_the_connection_is_lost() -> None:
    point = Point()
    point.read(8.0)
    point.read(8.0)
    point.silence(timedelta(minutes=10))
    point.read(8.0, after=timedelta(minutes=10))
    assert point.state.deviation_since == point.moment  # a new series starts


def test_late_and_out_of_order_readings_are_not_live() -> None:
    state = PointState(point_id=uuid.uuid4(), last_measured_at=T0)
    assert is_live(state, SETTINGS, T0 + MINUTE, T0 + MINUTE)
    assert not is_live(state, SETTINGS, T0 - MINUTE, T0)  # older than the current value
    assert not is_live(state, SETTINGS, T0 + MINUTE, T0 + 10 * MINUTE)  # arrived too late


def test_jump_to_the_other_side_closes_and_restarts() -> None:
    point = Point()
    for _ in range(7):
        point.read(9.0)
    point.read(0.0)
    assert len(point.closed(IncidentType.TEMPERATURE)) == 1
    assert point.status() is PointStatus.PENDING
