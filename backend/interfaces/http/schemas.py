"""Request and response bodies of the HTTP API (the OpenAPI schema the frontend types are generated from)."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.application.views import (
    AuthContext,
    EventView,
    IncidentView,
    JournalTable,
    PointOverview,
    RawTable,
    SensorView,
    SeriesPoint,
)
from backend.domain.equipment import (
    Equipment,
    EquipmentKind,
    MeasurementPoint,
    PointLocation,
    Room,
    SettingsProfile,
    Site,
)
from backend.domain.incidents import DeliveryStatus, EventKind, Recipient
from backend.domain.journal import ControlState
from backend.domain.monitoring import Direction, IncidentType, PointStatus
from backend.domain.organizations import Role
from backend.domain.sensors import Assignment, MeasurementSource, SensorKind

Name = Annotated[str, Field(min_length=1, max_length=200)]


class Model(BaseModel):
    """Strict base: unknown fields in requests are errors."""

    model_config = ConfigDict(extra="forbid")


class ErrorOut(Model):
    """Error body."""

    detail: str


class LoginIn(Model):
    """Sign-in form."""

    login: Annotated[str, Field(min_length=1, max_length=100)]
    password: Annotated[str, Field(min_length=1, max_length=500)]


class SessionOut(Model):
    """The signed-in user; ``csrf_token`` must be sent in ``X-CSRF-Token`` with every change."""

    login: str
    role: Role
    organization_id: UUID
    organization_name: str
    csrf_token: str
    public_demo: bool = False

    @classmethod
    def of(cls, context: AuthContext) -> SessionOut:
        """From the use case result."""
        return cls(
            login=context.login,
            role=context.role,
            organization_id=context.organization_id,
            organization_name=context.organization_name,
            csrf_token=context.csrf_token,
        )


class MetaOut(Model):
    """Facts the interface shows (setup instructions, dry-run notice)."""

    environment: str
    ingest_url: str
    bot_configured: bool
    bot_username: str | None


class SiteIn(Model):
    """Create or edit a site."""

    name: Name
    address: Annotated[str, Field(max_length=500)] = ""
    timezone: Annotated[str, Field(min_length=1, max_length=64)] = "Asia/Vladivostok"
    control_time: time = time(10, 0)
    control_window_minutes: Annotated[int, Field(ge=1, le=360)] = 30


class SiteOut(Model):
    """Site."""

    id: UUID
    name: str
    address: str
    timezone: str
    control_time: time
    control_window_minutes: int

    @classmethod
    def of(cls, site: Site) -> SiteOut:
        """From the domain."""
        return cls(
            id=site.id,
            name=site.name,
            address=site.address,
            timezone=site.timezone,
            control_time=site.control_time,
            control_window_minutes=int(site.control_window.total_seconds() // 60),
        )


class RoomIn(Model):
    """Create or edit a room."""

    site_id: UUID
    name: Name


class RoomOut(Model):
    """Room."""

    id: UUID
    site_id: UUID
    name: str

    @classmethod
    def of(cls, room: Room) -> RoomOut:
        """From the domain."""
        return cls(id=room.id, site_id=room.site_id, name=room.name)


class EquipmentIn(Model):
    """Create or edit equipment."""

    room_id: UUID
    name: Name
    kind: EquipmentKind = EquipmentKind.REFRIGERATOR


class EquipmentOut(Model):
    """Equipment."""

    id: UUID
    room_id: UUID
    name: str
    kind: EquipmentKind

    @classmethod
    def of(cls, equipment: Equipment) -> EquipmentOut:
        """From the domain."""
        return cls(id=equipment.id, room_id=equipment.room_id, name=equipment.name, kind=equipment.kind)


class PointSettingsBody(Model):
    """Monitoring settings of a point (durations in seconds)."""

    low_threshold: float
    high_threshold: float
    deviation_seconds: Annotated[int, Field(ge=0, le=86_400)] = 300
    recovery_seconds: Annotated[int, Field(ge=0, le=86_400)] = 120
    expected_interval_seconds: Annotated[int, Field(ge=10, le=86_400)] = 60
    offline_timeout_seconds: Annotated[int, Field(ge=20, le=604_800)] = 300
    profile: SettingsProfile = SettingsProfile.NORMAL


class PointIn(Model):
    """Create or edit a point."""

    equipment_id: UUID
    name: Name
    settings: PointSettingsBody


class PointOut(Model):
    """Point."""

    id: UUID
    equipment_id: UUID
    name: str
    settings: PointSettingsBody

    @classmethod
    def of(cls, point: MeasurementPoint) -> PointOut:
        """From the domain."""
        settings = point.settings
        return cls(
            id=point.id,
            equipment_id=point.equipment_id,
            name=point.name,
            settings=PointSettingsBody(
                low_threshold=settings.low_threshold,
                high_threshold=settings.high_threshold,
                deviation_seconds=int(settings.deviation_duration.total_seconds()),
                recovery_seconds=int(settings.recovery_duration.total_seconds()),
                expected_interval_seconds=int(settings.expected_interval.total_seconds()),
                offline_timeout_seconds=int(settings.offline_timeout.total_seconds()),
                profile=settings.profile,
            ),
        )


class InventoryOut(Model):
    """Whole inventory of the organization."""

    sites: list[SiteOut]
    rooms: list[RoomOut]
    equipment: list[EquipmentOut]
    points: list[PointOut]


class LocationOut(Model):
    """Path of a point."""

    site_id: UUID
    site_name: str
    timezone: str
    room_id: UUID
    room_name: str
    equipment_id: UUID
    equipment_name: str
    point_id: UUID
    point_name: str

    @classmethod
    def of(cls, location: PointLocation) -> LocationOut:
        """From the domain."""
        return cls(
            site_id=location.site_id,
            site_name=location.site_name,
            timezone=location.timezone,
            room_id=location.room_id,
            room_name=location.room_name,
            equipment_id=location.equipment_id,
            equipment_name=location.equipment_name,
            point_id=location.point_id,
            point_name=location.point_name,
        )


class CurrentSensorOut(Model):
    """Sensor of a point."""

    sensor_id: UUID
    hardware_id: str
    kind: SensorKind
    since: datetime


class PointOverviewOut(Model):
    """A point with its live status."""

    location: LocationOut
    settings: PointSettingsBody
    status: PointStatus
    last_temperature: float | None
    last_measured_at: datetime | None
    last_received_at: datetime | None
    pending_since: datetime | None
    alarm_direction: Direction | None
    sensor: CurrentSensorOut | None
    open_incidents: int
    is_demo: bool

    @classmethod
    def of(cls, point: PointOverview) -> PointOverviewOut:
        """From the use case result."""
        settings = PointOut.of(
            MeasurementPoint(
                id=point.record.location.point_id,
                equipment_id=point.record.location.equipment_id,
                name=point.record.location.point_name,
                settings=point.record.settings,
            ),
        ).settings
        sensor = point.sensor
        return cls(
            location=LocationOut.of(point.record.location),
            settings=settings,
            status=point.status,
            last_temperature=point.state.last_temperature,
            last_measured_at=point.state.last_measured_at,
            last_received_at=point.state.last_received_at,
            pending_since=point.state.deviation_since,
            alarm_direction=point.state.temperature_alarm,
            sensor=(
                None
                if sensor is None
                else CurrentSensorOut(
                    sensor_id=sensor.sensor_id,
                    hardware_id=sensor.hardware_id,
                    kind=sensor.kind,
                    since=sensor.since,
                )
            ),
            open_incidents=point.open_incidents,
            is_demo=point.is_demo,
        )


class EquipmentCardOut(Model):
    """Equipment card."""

    equipment: EquipmentOut
    points: list[PointOverviewOut]


class SeriesPointOut(Model):
    """Chart point; ``temperature`` is null for a probe failure."""

    t: datetime
    value: float | None
    ok: bool
    source: MeasurementSource

    @classmethod
    def of(cls, point: SeriesPoint) -> SeriesPointOut:
        """From the use case result."""
        return cls(t=point.measured_at, value=point.temperature, ok=point.sensor_ok, source=point.source)


class SensorIn(Model):
    """Register a sensor."""

    hardware_id: Annotated[str, Field(min_length=1, max_length=64)]
    kind: SensorKind = SensorKind.PHYSICAL
    model: Annotated[str, Field(max_length=100)] = "UnitX-T"


class TokenOut(Model):
    """A device token shown once."""

    sensor_id: UUID
    token: str
    ingest_url: str


class AssignmentIn(Model):
    """Assign a sensor to a point from ``starts_at`` (now by default)."""

    point_id: UUID
    starts_at: datetime | None = None


class AssignmentOut(Model):
    """Assignment period."""

    id: UUID
    point_id: UUID
    starts_at: datetime
    ends_at: datetime | None

    @classmethod
    def of(cls, assignment: Assignment) -> AssignmentOut:
        """From the domain."""
        return cls(
            id=assignment.id,
            point_id=assignment.point_id,
            starts_at=assignment.starts_at,
            ends_at=assignment.ends_at,
        )


class SensorOut(Model):
    """Sensor with current assignment and last contact."""

    id: UUID
    hardware_id: str
    kind: SensorKind
    model: str
    has_token: bool
    token_issued_at: datetime | None
    created_at: datetime
    assignment: AssignmentOut | None
    point: LocationOut | None
    last_measured_at: datetime | None
    last_temperature: float | None
    last_sensor_ok: bool | None
    last_unassigned: bool

    @classmethod
    def of(cls, view: SensorView) -> SensorOut:
        """From the use case result."""
        sensor = view.sensor
        return cls(
            id=sensor.id,
            hardware_id=sensor.hardware_id,
            kind=sensor.kind,
            model=sensor.model,
            has_token=sensor.token_hash is not None,
            token_issued_at=sensor.token_issued_at,
            created_at=sensor.created_at,
            assignment=None if view.assignment is None else AssignmentOut.of(view.assignment),
            point=None if view.point is None else LocationOut.of(view.point),
            last_measured_at=view.last_measured_at,
            last_temperature=view.last_temperature,
            last_sensor_ok=view.last_sensor_ok,
            last_unassigned=view.last_unassigned,
        )


class SensorDetailOut(Model):
    """Sensor with assignment history."""

    sensor: SensorOut
    history: list[AssignmentOut]


class JournalRowOut(Model):
    """One "date × point" row."""

    location: LocationOut
    day: date
    control_state: ControlState
    control_measured_at: datetime | None
    control_temperature: float | None
    minimum: float | None
    maximum: float | None
    valid_count: int
    error_count: int
    coverage: float
    sources: list[MeasurementSource]


class JournalOut(Model):
    """Daily journal."""

    organization_name: str
    first_day: date
    last_day: date
    has_simulation: bool
    rows: list[JournalRowOut]

    @classmethod
    def of(cls, table: JournalTable) -> JournalOut:
        """From the use case result."""
        return cls(
            organization_name=table.organization_name,
            first_day=table.first_day,
            last_day=table.last_day,
            has_simulation=table.has_simulation,
            rows=[
                JournalRowOut(
                    location=LocationOut.of(row.location),
                    day=row.day,
                    control_state=row.control.state,
                    control_measured_at=row.control.measured_at,
                    control_temperature=row.control.temperature,
                    minimum=row.stats.minimum,
                    maximum=row.stats.maximum,
                    valid_count=row.stats.valid_count,
                    error_count=row.stats.error_count,
                    coverage=round(row.coverage, 4),
                    sources=sorted(row.sources),
                )
                for row in table.rows
            ],
        )


class RawRowOut(Model):
    """Raw measurement."""

    location: LocationOut
    sensor_hardware_id: str
    measured_at: datetime
    received_at: datetime
    temperature: float | None
    sensor_ok: bool
    source: MeasurementSource
    humidity: float | None


class RawOut(Model):
    """Raw measurements of a period."""

    organization_name: str
    first_day: date
    last_day: date
    has_simulation: bool
    total: int
    rows: list[RawRowOut]

    @classmethod
    def of(cls, table: RawTable, limit: int) -> RawOut:
        """Screen view: the newest ``limit`` rows; the export contains all of them."""
        newest = sorted(table.rows, key=lambda row: row.measured_at, reverse=True)[:limit]
        return cls(
            organization_name=table.organization_name,
            first_day=table.first_day,
            last_day=table.last_day,
            has_simulation=table.has_simulation,
            total=len(table.rows),
            rows=[
                RawRowOut(
                    location=LocationOut.of(row.location),
                    sensor_hardware_id=row.sensor_hardware_id,
                    measured_at=row.measured_at,
                    received_at=row.received_at,
                    temperature=row.temperature,
                    sensor_ok=row.sensor_ok,
                    source=row.source,
                    humidity=row.humidity,
                )
                for row in newest
            ],
        )


class DeliveryOut(Model):
    """Delivery to one recipient."""

    recipient_title: str
    status: DeliveryStatus
    attempts: int
    last_error: str | None


class EventOut(Model):
    """Notification event."""

    kind: EventKind
    text: str
    created_at: datetime
    deliveries: list[DeliveryOut]

    @classmethod
    def of(cls, event: EventView) -> EventOut:
        """From the use case result."""
        return cls(
            kind=event.kind,
            text=event.text,
            created_at=event.created_at,
            deliveries=[
                DeliveryOut(
                    recipient_title=delivery.recipient_title,
                    status=delivery.status,
                    attempts=delivery.attempts,
                    last_error=delivery.last_error,
                )
                for delivery in event.deliveries
            ],
        )


class IncidentOut(Model):
    """Incident with notifications."""

    id: UUID
    type: IncidentType
    direction: Direction | None
    opened_at: datetime
    closed_at: datetime | None
    open_temperature: float | None
    close_temperature: float | None
    location: LocationOut
    events: list[EventOut]

    @classmethod
    def of(cls, view: IncidentView) -> IncidentOut:
        """From the use case result."""
        incident = view.incident
        return cls(
            id=incident.id,
            type=incident.type,
            direction=incident.direction,
            opened_at=incident.opened_at,
            closed_at=incident.closed_at,
            open_temperature=incident.open_temperature,
            close_temperature=incident.close_temperature,
            location=LocationOut.of(view.location),
            events=[EventOut.of(event) for event in view.events],
        )


class RecipientOut(Model):
    """Telegram recipient."""

    id: UUID
    chat_id: int
    title: str
    is_active: bool
    created_at: datetime

    @classmethod
    def of(cls, recipient: Recipient) -> RecipientOut:
        """From the domain."""
        return cls(
            id=recipient.id,
            chat_id=recipient.chat_id,
            title=recipient.title,
            is_active=recipient.is_active,
            created_at=recipient.created_at,
        )


class RecipientsOut(Model):
    """Recipients and bot status."""

    bot_configured: bool
    bot_username: str | None
    recipients: list[RecipientOut]


class RecipientActiveIn(Model):
    """Pause or resume a recipient."""

    active: bool


class BindingCodeOut(Model):
    """One-time binding code."""

    code: str
    expires_at: datetime
    deep_link: str | None


class HealthOut(Model):
    """Health check."""

    status: str
    database: bool
