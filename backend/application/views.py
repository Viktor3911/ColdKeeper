"""Read models returned by use cases to the interfaces (no ORM or HTTP types)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from backend.domain.equipment import (
    Equipment,
    MeasurementPoint,
    PointLocation,
    PointSettings,
    Room,
    SettingsProfile,
    Site,
)
from backend.domain.incidents import DeliveryStatus, EventKind, Incident
from backend.domain.journal import JournalRow
from backend.domain.monitoring import PointState, PointStatus
from backend.domain.organizations import Role
from backend.domain.sensors import Assignment, MeasurementSource, Sensor, SensorKind


@dataclass(frozen=True, slots=True)
class PointRecord:
    """A point with its location and settings, as storage returns it."""

    location: PointLocation
    settings: PointSettings


@dataclass(frozen=True, slots=True)
class CurrentSensor:
    """The sensor assigned to a point right now."""

    sensor_id: UUID
    hardware_id: str
    kind: SensorKind
    since: datetime


@dataclass(frozen=True, slots=True)
class PointOverview:
    """A point on the overview and equipment screens."""

    record: PointRecord
    state: PointState
    status: PointStatus
    sensor: CurrentSensor | None
    open_incidents: int

    @property
    def is_demo(self) -> bool:
        """Simulated sensor or demo timeouts — marked in the interface."""
        simulated = self.sensor is not None and self.sensor.kind is SensorKind.SIMULATED
        return simulated or self.record.settings.profile is SettingsProfile.DEMO


@dataclass(frozen=True, slots=True)
class SitesTree:
    """Inventory of an organization."""

    sites: list[Site]
    rooms: list[Room]
    equipment: list[Equipment]
    points: list[MeasurementPoint]


@dataclass(frozen=True, slots=True)
class SensorView:
    """A sensor with its current assignment and last contact."""

    sensor: Sensor
    assignment: Assignment | None
    point: PointLocation | None
    last_measured_at: datetime | None
    last_temperature: float | None
    last_sensor_ok: bool | None
    last_unassigned: bool


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A device token shown once; only its hash is stored."""

    sensor_id: UUID
    token: str


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    """One chart point; ``temperature`` is ``None`` for a failed probe reading."""

    measured_at: datetime
    temperature: float | None
    sensor_ok: bool
    source: MeasurementSource


@dataclass(frozen=True, slots=True)
class RawRow:
    """A raw measurement for the raw journal and its export."""

    location: PointLocation
    sensor_hardware_id: str
    measured_at: datetime
    received_at: datetime
    temperature: float | None
    sensor_ok: bool
    source: MeasurementSource
    humidity: float | None


@dataclass(frozen=True, slots=True)
class JournalTable:
    """The daily journal of a period."""

    organization_name: str
    first_day: date
    last_day: date
    rows: list[JournalRow]

    @property
    def has_simulation(self) -> bool:
        """Simulated data present — the export file and the screen are marked."""
        return any(MeasurementSource.SIMULATOR in row.sources for row in self.rows)


@dataclass(frozen=True, slots=True)
class RawTable:
    """Raw measurements of a period."""

    organization_name: str
    first_day: date
    last_day: date
    rows: list[RawRow]

    @property
    def has_simulation(self) -> bool:
        """Simulated data present."""
        return any(row.source is MeasurementSource.SIMULATOR for row in self.rows)


@dataclass(frozen=True, slots=True)
class DeliveryView:
    """Delivery of an event to one recipient."""

    recipient_title: str
    status: DeliveryStatus
    attempts: int
    last_error: str | None


@dataclass(frozen=True, slots=True)
class EventView:
    """A notification event and its deliveries (possibly none)."""

    kind: EventKind
    text: str
    created_at: datetime
    deliveries: list[DeliveryView]


@dataclass(frozen=True, slots=True)
class IncidentView:
    """An incident with its location and notifications."""

    incident: Incident
    location: PointLocation
    events: list[EventView]


@dataclass(frozen=True, slots=True)
class AuthContext:
    """The signed-in user of a request."""

    user_id: UUID
    organization_id: UUID
    organization_name: str
    login: str
    role: Role
    csrf_token: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    """A new session; ``session_token`` goes to the HttpOnly cookie only."""

    session_token: str
    context: AuthContext


@dataclass(frozen=True, slots=True)
class BindingCode:
    """A one-time code for linking a Telegram chat; shown once."""

    code: str
    expires_at: datetime
    deep_link: str | None
