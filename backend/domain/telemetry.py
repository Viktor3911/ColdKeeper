"""The vendor-neutral reading every input adapter produces, and stored measurements."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from backend.domain.equipment import PROBE_MAX_C, PROBE_MIN_C
from backend.domain.errors import ValidationFailedError
from backend.domain.sensors import MeasurementSource

# Readings further in the future than this are rejected: the device clock is wrong.
MAX_CLOCK_SKEW = timedelta(minutes=5)
# Older readings are rejected; they cannot be confirmed and would not fit a journal correction anyway.
MAX_READING_AGE = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class Reading:
    """One measurement as reported by a device, already normalized to UTC and °C.

    ``sensor_ok=False`` is a probe failure: the temperature is unknown (``None``), never 0 °C.
    """

    hardware_id: str
    measured_at: datetime
    temperature: float | None
    sensor_ok: bool
    humidity: float | None = None
    rssi: int | None = None

    def __post_init__(self) -> None:
        if self.measured_at.utcoffset() != timedelta(0):
            raise ValidationFailedError("Время измерения должно быть в UTC")
        if self.sensor_ok:
            if self.temperature is None:
                raise ValidationFailedError("При ok=true температура обязательна")
            if not math.isfinite(self.temperature) or not PROBE_MIN_C <= self.temperature <= PROBE_MAX_C:
                raise ValidationFailedError("Температура вне диапазона датчика")
        elif self.temperature is not None:
            raise ValidationFailedError("При ok=false температура должна отсутствовать")
        if self.humidity is not None and (not math.isfinite(self.humidity) or not 0 <= self.humidity <= 100):
            raise ValidationFailedError("Влажность вне диапазона 0…100 %")

    def check_time(self, now: datetime) -> None:
        """Reject readings from a wrong device clock or too far in the past."""
        if self.measured_at > now + MAX_CLOCK_SKEW:
            raise ValidationFailedError("Время измерения в будущем: проверьте часы устройства")
        if self.measured_at < now - MAX_READING_AGE:
            raise ValidationFailedError("Измерение старше 30 суток не принимается")


@dataclass(frozen=True, slots=True)
class Measurement:
    """A stored measurement; ``point_id`` is ``None`` when the sensor had no assignment at that moment."""

    sensor_id: UUID
    assignment_id: UUID | None
    point_id: UUID | None
    measured_at: datetime
    received_at: datetime
    temperature: float | None
    sensor_ok: bool
    source: MeasurementSource
    humidity: float | None = None
    rssi: int | None = None

    @property
    def is_valid(self) -> bool:
        """A usable temperature value (the probe responded)."""
        return self.sensor_ok and self.temperature is not None

    def same_reading(self, reading: Reading) -> bool:
        """Whether a repeated request carries the same values (an idempotent retry)."""
        return (
            self.sensor_ok == reading.sensor_ok
            and _same_number(self.temperature, reading.temperature)
            and _same_number(self.humidity, reading.humidity)
        )


def round_temperature(value: float | None) -> float | None:
    """Storage precision: hundredths of a degree."""
    return None if value is None else round(value, 2)


def _same_number(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(left - round(right, 2)) < 0.005
