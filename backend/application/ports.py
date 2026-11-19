"""Interfaces the use cases depend on; adapters implement them, ``composition.py`` wires them.

Every repository method that serves a user request takes ``organization_id`` and filters by it in the query,
so an id from a URL alone never grants access.
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from uuid import UUID

from backend.application.journal_form import TemperatureForm
from backend.application.views import (
    CurrentSensor,
    EventView,
    JournalTable,
    PointRecord,
    RawRow,
    RawTable,
    SeriesPoint,
)
from backend.domain.auth import LoginAttempts, UserSession
from backend.domain.equipment import Equipment, MeasurementPoint, Room, Site
from backend.domain.incidents import Delivery, DeliveryStatus, Incident, NotificationEvent, Recipient
from backend.domain.journal import DayRange, DayStats, WindowReading
from backend.domain.monitoring import IncidentType, PointState
from backend.domain.organizations import Organization, User
from backend.domain.sensors import Assignment, Sensor
from backend.domain.telemetry import Measurement


class Clock(Protocol):
    """Source of the current time (UTC, timezone-aware)."""

    def now(self) -> datetime:
        """Return the current moment."""
        ...


class SystemClock:
    """The real wall clock."""

    def now(self) -> datetime:
        """Current UTC time."""
        return datetime.now(tz=UTC)


class PasswordHasher(Protocol):
    """Slow password hashing; CPU-bound, so callers run it in a worker thread."""

    def hash(self, password: str) -> str:
        """Hash with a fresh salt."""
        ...

    def verify(self, password: str, encoded: str) -> bool:
        """Constant-time check of a password against a stored hash."""
        ...

    def needs_rehash(self, encoded: str) -> bool:
        """Whether the stored hash uses outdated parameters."""
        ...


class SecretIssuer(Protocol):
    """Random secrets (device tokens, session ids, binding codes) and their storage hashes."""

    def new_token(self) -> str:
        """URL-safe random token."""
        ...

    def new_code(self) -> str:
        """Short one-time code a person can type."""
        ...

    def digest(self, secret: str) -> str:
        """Hash stored instead of the secret."""
        ...


class DeliveryError(Exception):
    """A delivery attempt failed; ``permanent`` failures are not retried."""

    def __init__(self, reason: str, *, permanent: bool = False, retry_after: timedelta | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.permanent = permanent
        self.retry_after = retry_after


class NotificationSender(Protocol):
    """Delivers a text message to a chat."""

    @property
    def is_dry_run(self) -> bool:
        """``True`` when nothing is really sent (no bot token)."""
        ...

    async def send(self, chat_id: int, text: str) -> None:
        """Send or raise :class:`DeliveryError`."""
        ...


@dataclass(frozen=True, slots=True)
class ExportFile:
    """A rendered export."""

    content: bytes
    media_type: str
    extension: str
    has_simulation: bool


class JournalExporter(Protocol):
    """Serializes journal tables into one file format."""

    def daily(self, table: JournalTable) -> ExportFile:
        """The daily journal."""
        ...

    def raw(self, table: RawTable) -> ExportFile:
        """Raw measurements."""
        ...


class InventoryKind(enum.StrEnum):
    """Inventory entity types."""

    SITE = "site"
    ROOM = "room"
    EQUIPMENT = "equipment"
    POINT = "point"


class JournalFormRenderer(Protocol):
    """The printable journal in the layout of SanPiN 2.3/2.4.4282-26, appendix N 2 (a Word document)."""

    def render(self, form: TemperatureForm) -> ExportFile:
        """All months of the form in one file."""
        ...


class OrganizationRepository(Protocol):
    """Client organizations."""

    async def add(self, organization: Organization) -> None:
        """Store a new organization."""
        ...

    async def get(self, organization_id: UUID) -> Organization | None:
        """By id."""
        ...

    async def get_by_name(self, name: str) -> Organization | None:
        """By exact name."""
        ...


class UserRepository(Protocol):
    """Users who sign in."""

    async def add(self, user: User) -> None:
        """Store a new user."""
        ...

    async def get(self, user_id: UUID) -> User | None:
        """By id."""
        ...

    async def get_by_login(self, login: str) -> User | None:
        """By normalized login."""
        ...

    async def set_password_hash(self, user_id: UUID, password_hash: str) -> None:
        """Replace the stored hash (rehash on sign-in, password change)."""
        ...


class SessionRepository(Protocol):
    """Server-side browser sessions."""

    async def add(self, session: UserSession) -> None:
        """Store a new session."""
        ...

    async def get(self, id_hash: str) -> UserSession | None:
        """By the hash of the cookie value."""
        ...

    async def touch(self, id_hash: str, moment: datetime) -> None:
        """Extend an active session."""
        ...

    async def delete(self, id_hash: str) -> None:
        """Sign out."""
        ...


class LoginAttemptRepository(Protocol):
    """Failed sign-in counters."""

    async def get(self, login: str, address: str) -> LoginAttempts | None:
        """Counter of a (login, address) pair."""
        ...

    async def save(self, login: str, address: str, attempts: LoginAttempts, moment: datetime) -> None:
        """Store the counter."""
        ...

    async def clear(self, login: str, address: str) -> None:
        """Reset after a successful sign-in."""
        ...


class InventoryRepository(Protocol):
    """Sites, rooms, equipment and measurement points of an organization."""

    async def sites(self, organization_id: UUID) -> list[Site]:
        """All sites, by name."""
        ...

    async def rooms(self, organization_id: UUID) -> list[Room]:
        """All rooms, by name."""
        ...

    async def equipment(self, organization_id: UUID) -> list[Equipment]:
        """All equipment, by name."""
        ...

    async def points(self, organization_id: UUID) -> list[MeasurementPoint]:
        """All points, by name."""
        ...

    async def get_site(self, organization_id: UUID, site_id: UUID) -> Site | None:
        """A site of the organization."""
        ...

    async def get_room(self, organization_id: UUID, room_id: UUID) -> Room | None:
        """A room of the organization."""
        ...

    async def get_equipment(self, organization_id: UUID, equipment_id: UUID) -> Equipment | None:
        """Equipment of the organization."""
        ...

    async def get_point(self, organization_id: UUID, point_id: UUID) -> MeasurementPoint | None:
        """A point of the organization."""
        ...

    async def save_site(self, organization_id: UUID, site: Site) -> None:
        """Insert or update."""
        ...

    async def save_room(self, room: Room) -> None:
        """Insert or update (the site is already checked)."""
        ...

    async def save_equipment(self, equipment: Equipment) -> None:
        """Insert or update (the room is already checked)."""
        ...

    async def save_point(self, point: MeasurementPoint) -> None:
        """Insert or update (the equipment is already checked)."""
        ...

    async def delete(self, kind: InventoryKind, entity_id: UUID) -> None:
        """Delete an empty site, room, equipment or point."""
        ...

    async def has_children(self, kind: InventoryKind, entity_id: UUID) -> bool:
        """Whether deleting would orphan rooms, equipment, points, assignments or measurements."""
        ...

    async def point_records(
        self,
        organization_id: UUID,
        *,
        site_id: UUID | None = None,
        equipment_id: UUID | None = None,
        point_ids: Sequence[UUID] | None = None,
    ) -> list[PointRecord]:
        """Points with location and settings, ordered site → room → equipment → point."""
        ...

    async def point_record(self, point_id: UUID) -> PointRecord | None:
        """Internal lookup for ingest and the worker (no organization filter: the caller is the system)."""
        ...


class SensorRepository(Protocol):
    """Registered devices."""

    async def add(self, sensor: Sensor) -> None:
        """Store a new sensor."""
        ...

    async def get(self, organization_id: UUID, sensor_id: UUID) -> Sensor | None:
        """A sensor of the organization."""
        ...

    async def for_organization(self, organization_id: UUID) -> list[Sensor]:
        """All sensors of the organization."""
        ...

    async def get_by_hardware_id(self, hardware_id: str) -> Sensor | None:
        """Across organizations: hardware ids are globally unique."""
        ...

    async def get_by_token_hash(self, token_hash: str) -> Sensor | None:
        """Authenticate a device."""
        ...

    async def set_token(self, sensor_id: UUID, token_hash: str | None, moment: datetime) -> None:
        """Replace or revoke (``None``) the token."""
        ...


class AssignmentRepository(Protocol):
    """Time-bounded sensor → point assignments."""

    async def add(self, assignment: Assignment) -> None:
        """Store an assignment; overlaps are rejected by the database."""
        ...

    async def at(self, sensor_id: UUID, moment: datetime) -> Assignment | None:
        """The assignment covering a measurement time."""
        ...

    async def open_for_sensor(self, sensor_id: UUID) -> Assignment | None:
        """The active assignment of a sensor."""
        ...

    async def open_for_point(self, point_id: UUID) -> Assignment | None:
        """The active assignment of a point."""
        ...

    async def close(self, assignment_id: UUID, ends_at: datetime) -> None:
        """End an assignment."""
        ...

    async def for_sensor(self, sensor_id: UUID) -> list[Assignment]:
        """History of a sensor, newest first."""
        ...

    async def current_sensors(self, point_ids: Sequence[UUID]) -> dict[UUID, CurrentSensor]:
        """Active sensor of each point."""
        ...


class MeasurementRepository(Protocol):
    """Stored measurements; ``(sensor_id, measured_at)`` is unique."""

    async def get(self, sensor_id: UUID, measured_at: datetime) -> Measurement | None:
        """The stored measurement with this key."""
        ...

    async def add(self, measurement: Measurement) -> bool:
        """Insert unless the key exists; returns whether a row was inserted."""
        ...

    async def latest_for_sensor(self, sensor_id: UUID) -> Measurement | None:
        """Newest measurement of a sensor (assigned or not)."""
        ...

    async def latest_for_point(self, point_id: UUID) -> Measurement | None:
        """Newest measurement of a point."""
        ...

    async def series(self, point_id: UUID, start: datetime, end: datetime) -> list[SeriesPoint]:
        """Chart data ``[start, end)`` ordered by time."""
        ...

    async def raw(self, point_ids: Sequence[UUID], start: datetime, end: datetime) -> list[RawRow]:
        """Raw rows ``[start, end)`` ordered by point then time (location is filled by the repository)."""
        ...

    async def day_stats(self, point_ids: Sequence[UUID], days: Sequence[DayRange]) -> dict[tuple[UUID, date], DayStats]:
        """Aggregates per point and local day."""
        ...

    async def in_windows(
        self,
        point_ids: Sequence[UUID],
        windows: Sequence[DayRange],
    ) -> dict[tuple[UUID, date], list[WindowReading]]:
        """Measurements inside the control windows, keyed by point and local day."""
        ...


class PointStateRepository(Protocol):
    """Live state of points, changed under a row lock."""

    async def lock(self, point_id: UUID) -> PointState:
        """Load (or create) the state and lock it until the end of the transaction."""
        ...

    async def save(self, state: PointState) -> None:
        """Persist a state loaded with :meth:`lock`."""
        ...

    async def get_many(self, point_ids: Sequence[UUID]) -> dict[UUID, PointState]:
        """Read without locking (overview)."""
        ...

    async def silent_candidates(self, now: datetime, limit: int) -> list[UUID]:
        """Points not marked offline whose last contact is older than their timeout."""
        ...


class IncidentRepository(Protocol):
    """Incidents; at most one open incident of each type per point."""

    async def open(self, incident: Incident) -> bool:
        """Insert an open incident; ``False`` if one of this type is already open."""
        ...

    async def get_open(self, point_id: UUID, incident_type: IncidentType) -> Incident | None:
        """The open incident of this type."""
        ...

    async def close(self, incident_id: UUID, closed_at: datetime, temperature: float | None) -> None:
        """Close an incident."""
        ...

    async def recent(self, organization_id: UUID, *, only_open: bool, limit: int) -> list[Incident]:
        """Newest first."""
        ...

    async def open_counts(self, point_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Open incidents per point."""
        ...


class RecipientRepository(Protocol):
    """Telegram chats bound to organizations, and binding codes."""

    async def active(self, organization_id: UUID) -> list[Recipient]:
        """Recipients who get notifications."""
        ...

    async def all_of(self, organization_id: UUID) -> list[Recipient]:
        """All recipients, including deactivated."""
        ...

    async def save(self, recipient: Recipient) -> None:
        """Upsert by organization and chat, keeping the original id and creation time."""
        ...

    async def add_code(self, organization_id: UUID, code_hash: str, expires_at: datetime) -> None:
        """Store a binding code hash."""
        ...

    async def consume_code(self, code_hash: str, now: datetime) -> UUID | None:
        """Mark an unexpired, unused code as used; return its organization."""
        ...


class NotificationRepository(Protocol):
    """Notification events and the delivery queue."""

    async def add_event(self, event: NotificationEvent, deliveries: Sequence[Delivery]) -> None:
        """Store an event with its deliveries."""
        ...

    async def claim_due(self, now: datetime) -> Delivery | None:
        """Lock the oldest due pending delivery (``SKIP LOCKED``) for this transaction."""
        ...

    async def update_delivery(
        self,
        delivery_id: UUID,
        *,
        status: DeliveryStatus,
        attempts: int,
        next_attempt_at: datetime,
        last_error: str | None,
        moment: datetime,
    ) -> None:
        """Record the outcome of an attempt."""
        ...

    async def events_for(self, incident_ids: Sequence[UUID]) -> dict[UUID, list[EventView]]:
        """Events and deliveries of incidents, oldest first."""
        ...


class UnitOfWork(Protocol):
    """One database transaction with the repositories bound to it; nothing is saved without :meth:`commit`."""

    @property
    def organizations(self) -> OrganizationRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def users(self) -> UserRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def sessions(self) -> SessionRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def login_attempts(self) -> LoginAttemptRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def inventory(self) -> InventoryRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def sensors(self) -> SensorRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def assignments(self) -> AssignmentRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def measurements(self) -> MeasurementRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def point_states(self) -> PointStateRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def incidents(self) -> IncidentRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def recipients(self) -> RecipientRepository:
        """Repository bound to this transaction."""
        ...

    @property
    def notifications(self) -> NotificationRepository:
        """Repository bound to this transaction."""
        ...

    async def __aenter__(self) -> UnitOfWork:
        """Begin."""
        ...

    async def __aexit__(self, *exc_info: object) -> None:
        """Roll back anything not committed."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...


class UnitOfWorkFactory(Protocol):
    """Creates a fresh unit of work per use case call."""

    def __call__(self) -> UnitOfWork:
        """New transaction scope."""
        ...
