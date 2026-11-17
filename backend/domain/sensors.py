"""Sensors (devices) and their time-bounded assignments to measurement points."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from backend.domain.errors import ValidationFailedError

_HARDWARE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")


class SensorKind(enum.StrEnum):
    """Fixed at registration; a switch to real hardware means a new sensor, so history keeps its label."""

    PHYSICAL = "physical"
    SIMULATED = "simulated"


class MeasurementSource(enum.StrEnum):
    """Label stored on every measurement, copied from the sensor registration — never trusted from the client."""

    DEVICE = "device"
    SIMULATOR = "simulator"


def source_of(kind: SensorKind) -> MeasurementSource:
    """Measurement label for a sensor kind."""
    return MeasurementSource.DEVICE if kind is SensorKind.PHYSICAL else MeasurementSource.SIMULATOR


def check_hardware_id(value: str) -> str:
    """Validate the vendor address, e.g. ``utx-ae4634``."""
    hardware_id = value.strip()
    if not _HARDWARE_ID.fullmatch(hardware_id):
        raise ValidationFailedError("Аппаратный ID: латиница, цифры и символы _ . : -, до 64 знаков")
    return hardware_id


@dataclass(frozen=True, slots=True)
class Sensor:
    """A registered device; only the hash of its token is stored."""

    id: UUID
    organization_id: UUID
    hardware_id: str
    kind: SensorKind
    model: str
    token_hash: str | None
    token_issued_at: datetime | None
    created_at: datetime

    @property
    def source(self) -> MeasurementSource:
        """Label for measurements of this sensor."""
        return source_of(self.kind)


@dataclass(frozen=True, slots=True)
class Assignment:
    """The sensor measures the point during ``[starts_at, ends_at)``; ``ends_at`` is ``None`` while active."""

    id: UUID
    sensor_id: UUID
    point_id: UUID
    starts_at: datetime
    ends_at: datetime | None

    def covers(self, moment: datetime) -> bool:
        """Whether a measurement taken at ``moment`` belongs to this assignment."""
        return self.starts_at <= moment and (self.ends_at is None or moment < self.ends_at)

    @property
    def is_open(self) -> bool:
        """The assignment has no end yet."""
        return self.ends_at is None
