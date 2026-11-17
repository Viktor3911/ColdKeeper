"""Daily journal rules: local days, the control measurement and daily statistics.

MVP rule (a setting, not a regulatory requirement): the control value of a day is the first valid measurement
within ``control_window`` after the site's ``control_time``; without one the day shows "нет данных".
"""

from __future__ import annotations

import enum
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from backend.domain.equipment import PointLocation
from backend.domain.errors import ValidationFailedError
from backend.domain.sensors import MeasurementSource

MAX_JOURNAL_DAYS = 366


@dataclass(frozen=True, slots=True)
class DayRange:
    """A local calendar day as a UTC interval ``[start, end)``; its length is 23–25 h around DST changes."""

    day: date
    start: datetime
    end: datetime

    @property
    def length(self) -> timedelta:
        """Real duration of the local day."""
        return self.end - self.start


def check_period(first: date, last: date) -> None:
    """Validate an inclusive range of local dates."""
    if last < first:
        raise ValidationFailedError("Дата окончания раньше даты начала")
    if (last - first).days + 1 > MAX_JOURNAL_DAYS:
        raise ValidationFailedError(f"Период журнала — не больше {MAX_JOURNAL_DAYS} дней")


def local_days(first: date, last: date, zone: ZoneInfo) -> list[DayRange]:
    """Every local day of the inclusive period, converted to UTC bounds."""
    check_period(first, last)
    days: list[DayRange] = []
    current = first
    while current <= last:
        start = datetime.combine(current, time.min, tzinfo=zone).astimezone(UTC)
        end = datetime.combine(current + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
        days.append(DayRange(current, start, end))
        current += timedelta(days=1)
    return days


def control_windows(days: Iterable[DayRange], zone: ZoneInfo, control_time: time, window: timedelta) -> list[DayRange]:
    """The control window of each day as UTC bounds (keyed by the same local date)."""
    windows: list[DayRange] = []
    for day in days:
        start = datetime.combine(day.day, control_time, tzinfo=zone).astimezone(UTC)
        windows.append(DayRange(day.day, start, start + window))
    return windows


class ControlState(enum.StrEnum):
    """What the control column shows."""

    OK = "ok"
    NO_DATA = "no_data"
    SENSOR_ERROR = "sensor_error"  # only failed readings inside the window


@dataclass(frozen=True, slots=True)
class WindowReading:
    """A measurement inside a control window."""

    measured_at: datetime
    temperature: float | None
    sensor_ok: bool
    source: MeasurementSource


@dataclass(frozen=True, slots=True)
class DayStats:
    """Aggregates of one point over one local day, computed by the storage over the given ranges."""

    valid_count: int = 0
    error_count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    sources: frozenset[MeasurementSource] = frozenset()


@dataclass(frozen=True, slots=True)
class ControlValue:
    """The chosen control measurement."""

    state: ControlState
    measured_at: datetime | None = None
    temperature: float | None = None


def pick_control(readings: Sequence[WindowReading]) -> ControlValue:
    """First valid measurement of the window; never a substitute such as the last or an average value."""
    ordered = sorted(readings, key=lambda reading: reading.measured_at)
    for reading in ordered:
        if reading.sensor_ok and reading.temperature is not None:
            return ControlValue(ControlState.OK, reading.measured_at, reading.temperature)
    if ordered:
        return ControlValue(ControlState.SENSOR_ERROR)
    return ControlValue(ControlState.NO_DATA)


def coverage(valid_count: int, expected_interval: timedelta, day_length: timedelta) -> float:
    """Estimated share of the day covered by valid readings (0…1), from their count and the expected interval."""
    if day_length <= timedelta(0):
        return 0.0
    return min(1.0, valid_count * expected_interval / day_length)


@dataclass(frozen=True, slots=True)
class JournalRow:
    """One "date × point" row of the daily journal."""

    location: PointLocation
    day: date
    control: ControlValue
    stats: DayStats
    coverage: float

    @property
    def sources(self) -> frozenset[MeasurementSource]:
        """Origins of the day's data (both while a point switched from simulation to a device)."""
        return self.stats.sources


def build_row(
    location: PointLocation,
    day: DayRange,
    window_readings: Sequence[WindowReading],
    stats: DayStats,
    expected_interval: timedelta,
) -> JournalRow:
    """Assemble a journal row from the storage aggregates and the control window readings."""
    return JournalRow(
        location=location,
        day=day.day,
        control=pick_control(window_readings),
        stats=stats,
        coverage=coverage(stats.valid_count, expected_interval, day.length),
    )
