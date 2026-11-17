"""Local days, control measurement and coverage."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.domain.errors import ValidationFailedError
from backend.domain.journal import (
    ControlState,
    WindowReading,
    control_windows,
    coverage,
    local_days,
    pick_control,
)
from backend.domain.sensors import MeasurementSource

VLADIVOSTOK = ZoneInfo("Asia/Vladivostok")


def _reading(hour: int, minute: int, temperature: float | None, *, ok: bool = True) -> WindowReading:
    moment = datetime(2026, 11, 3, hour, minute, tzinfo=VLADIVOSTOK).astimezone(UTC)
    return WindowReading(moment, temperature, ok, MeasurementSource.DEVICE)


def test_local_days_use_the_site_zone() -> None:
    days = local_days(date(2026, 11, 3), date(2026, 11, 4), VLADIVOSTOK)
    assert [day.day for day in days] == [date(2026, 11, 3), date(2026, 11, 4)]
    assert days[0].start == datetime(2026, 11, 2, 14, 0, tzinfo=UTC)  # 00:00 at UTC+10
    assert days[0].length == timedelta(hours=24)


def test_days_around_a_dst_change_have_their_real_length() -> None:
    berlin = ZoneInfo("Europe/Berlin")
    (day,) = local_days(date(2026, 3, 29), date(2026, 3, 29), berlin)
    assert day.length == timedelta(hours=23)


def test_control_window_is_local_time() -> None:
    days = local_days(date(2026, 11, 3), date(2026, 11, 3), VLADIVOSTOK)
    (window,) = control_windows(days, VLADIVOSTOK, time(10, 0), timedelta(minutes=30))
    assert window.start == datetime(2026, 11, 3, 0, 0, tzinfo=UTC)
    assert window.end - window.start == timedelta(minutes=30)


def test_first_valid_measurement_in_the_window_is_the_control_value() -> None:
    control = pick_control([_reading(10, 7, 4.6), _reading(10, 2, None, ok=False), _reading(10, 4, 4.1)])
    assert control.state is ControlState.OK
    assert control.temperature == 4.1
    assert control.measured_at == _reading(10, 4, 4.1).measured_at


def test_no_value_is_invented() -> None:
    assert pick_control([]).state is ControlState.NO_DATA
    only_errors = pick_control([_reading(10, 1, None, ok=False)])
    assert only_errors.state is ControlState.SENSOR_ERROR
    assert only_errors.temperature is None


def test_coverage_is_bounded() -> None:
    assert coverage(1440, timedelta(minutes=1), timedelta(hours=24)) == 1.0
    assert coverage(720, timedelta(minutes=1), timedelta(hours=24)) == 0.5
    assert coverage(5000, timedelta(minutes=1), timedelta(hours=24)) == 1.0


def test_period_limits() -> None:
    with pytest.raises(ValidationFailedError):
        local_days(date(2026, 11, 4), date(2026, 11, 3), VLADIVOSTOK)
    with pytest.raises(ValidationFailedError):
        local_days(date(2024, 1, 1), date(2026, 1, 1), VLADIVOSTOK)
