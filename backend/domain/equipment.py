"""Where measurements happen: site → room → equipment → measurement point."""

from __future__ import annotations

import enum
import math
from dataclasses import dataclass
from datetime import time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.domain.errors import ValidationFailedError

DEFAULT_TIMEZONE = "Asia/Vladivostok"
DEFAULT_CONTROL_TIME = time(10, 0)
DEFAULT_CONTROL_WINDOW = timedelta(minutes=30)

# Physical range of the DS18B20 probe; thresholds outside it can never be reached.
PROBE_MIN_C = -55.0
PROBE_MAX_C = 125.0
MAX_NAME_LENGTH = 200


def clean_name(value: str, what: str) -> str:
    """Trim a display name and check it is neither empty nor too long."""
    name = value.strip()
    if not name:
        raise ValidationFailedError(f"Укажите {what}")
    if len(name) > MAX_NAME_LENGTH:
        raise ValidationFailedError(f"Слишком длинное значение: {what}")
    return name


def check_timezone(name: str) -> str:
    """Accept only IANA zone names known to the bundled tz database."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValidationFailedError(f"Неизвестный часовой пояс: {name}") from error
    return name


class EquipmentKind(enum.StrEnum):
    """Type of cold equipment; a hint for the interface, not a temperature norm."""

    REFRIGERATOR = "refrigerator"
    FREEZER = "freezer"
    COMBINED = "combined"
    COLD_ROOM = "cold_room"
    DISPLAY = "display"
    OTHER = "other"


class SettingsProfile(enum.StrEnum):
    """``demo`` marks the shortened timeouts used for live demonstrations."""

    NORMAL = "normal"
    DEMO = "demo"


@dataclass(frozen=True, slots=True)
class Site:
    """A client's address; journal days and the control time use its time zone."""

    id: UUID
    organization_id: UUID
    name: str
    address: str
    timezone: str
    control_time: time
    control_window: timedelta

    @property
    def zone(self) -> ZoneInfo:
        """Time zone object for local dates."""
        return ZoneInfo(self.timezone)


@dataclass(frozen=True, slots=True)
class Room:
    """A room at a site."""

    id: UUID
    site_id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class Equipment:
    """A refrigerator, freezer or cold room."""

    id: UUID
    room_id: UUID
    name: str
    kind: EquipmentKind


@dataclass(frozen=True, slots=True)
class PointSettings:
    """Monitoring rules of one measurement point; MVP defaults are adjustable, not a norm."""

    low_threshold: float
    high_threshold: float
    deviation_duration: timedelta = timedelta(minutes=5)
    recovery_duration: timedelta = timedelta(minutes=2)
    expected_interval: timedelta = timedelta(seconds=60)
    offline_timeout: timedelta = timedelta(minutes=5)
    profile: SettingsProfile = SettingsProfile.NORMAL

    def __post_init__(self) -> None:
        for value in (self.low_threshold, self.high_threshold):
            if not math.isfinite(value) or not PROBE_MIN_C <= value <= PROBE_MAX_C:
                raise ValidationFailedError(f"Порог должен быть в диапазоне {PROBE_MIN_C:g}…{PROBE_MAX_C:g} °C")
        if self.low_threshold >= self.high_threshold:
            raise ValidationFailedError("Нижний порог должен быть меньше верхнего")
        if self.expected_interval < timedelta(seconds=10):
            raise ValidationFailedError("Ожидаемый интервал показаний — не меньше 10 секунд")
        if self.deviation_duration < timedelta(0) or self.recovery_duration < timedelta(0):
            raise ValidationFailedError("Длительности не могут быть отрицательными")
        if self.offline_timeout < 2 * self.expected_interval:
            raise ValidationFailedError("Таймаут связи должен быть не меньше двух ожидаемых интервалов")

    @property
    def gap_limit(self) -> timedelta:
        """A longer pause between readings breaks the continuity of a deviation or a recovery."""
        return self.expected_interval * 5 / 2

    @property
    def late_threshold(self) -> timedelta:
        """Readings older than this on arrival are history: stored, but do not change the live status."""
        return self.expected_interval * 2


@dataclass(frozen=True, slots=True)
class MeasurementPoint:
    """A place inside equipment where a probe measures temperature (e.g. the freezer section)."""

    id: UUID
    equipment_id: UUID
    name: str
    settings: PointSettings


@dataclass(frozen=True, slots=True)
class PointLocation:
    """Human-readable path of a point for messages, journal rows and exports."""

    organization_id: UUID
    organization_name: str
    site_id: UUID
    site_name: str
    timezone: str
    room_id: UUID
    room_name: str
    equipment_id: UUID
    equipment_name: str
    point_id: UUID
    point_name: str

    @property
    def zone(self) -> ZoneInfo:
        """Time zone of the site."""
        return ZoneInfo(self.timezone)
