"""SQLAlchemy tables. Constraints that guard business rules are named; see the migrations for EXCLUDE ranges."""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

Temperature = Numeric(6, 2, asdecimal=False)
Moment = DateTime(timezone=True)


class Base(DeclarativeBase):
    """Declarative base with a stable constraint naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class OrganizationRow(Base):
    """Client organization."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(Moment)


class UserRow(Base):
    """Web user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    login: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(Moment)


class SessionRow(Base):
    """Browser session (hash of the cookie value)."""

    __tablename__ = "sessions"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(Moment)
    last_seen_at: Mapped[datetime] = mapped_column(Moment)


class LoginAttemptRow(Base):
    """Failed sign-in counter per login and client address."""

    __tablename__ = "login_attempts"

    login: Mapped[str] = mapped_column(String(100), primary_key=True)
    address: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer)
    locked_until: Mapped[datetime | None] = mapped_column(Moment)
    updated_at: Mapped[datetime] = mapped_column(Moment)


class SiteRow(Base):
    """Site (address) of an organization."""

    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(String(64))
    control_time: Mapped[time] = mapped_column(Time)
    control_window_minutes: Mapped[int] = mapped_column(Integer)


class RoomRow(Base):
    """Room of a site."""

    __tablename__ = "rooms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))


class EquipmentRow(Base):
    """Refrigerator, freezer or cold room."""

    __tablename__ = "equipment"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))


class PointRow(Base):
    """Measurement point with its monitoring settings."""

    __tablename__ = "points"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    equipment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("equipment.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    low_threshold: Mapped[float] = mapped_column(Temperature)
    high_threshold: Mapped[float] = mapped_column(Temperature)
    deviation_seconds: Mapped[int] = mapped_column(Integer)
    recovery_seconds: Mapped[int] = mapped_column(Integer)
    expected_interval_seconds: Mapped[int] = mapped_column(Integer)
    offline_timeout_seconds: Mapped[int] = mapped_column(Integer)
    profile: Mapped[str] = mapped_column(String(20))


class SensorRow(Base):
    """Registered device; ``kind`` never changes after registration."""

    __tablename__ = "sensors"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    hardware_id: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    model: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    token_issued_at: Mapped[datetime | None] = mapped_column(Moment)
    created_at: Mapped[datetime] = mapped_column(Moment)


class AssignmentRow(Base):
    """Sensor → point during ``[starts_at, ends_at)``; overlaps are excluded by GiST constraints (migration)."""

    __tablename__ = "sensor_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    sensor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sensors.id"), index=True)
    point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("points.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(Moment)
    ends_at: Mapped[datetime | None] = mapped_column(Moment)


class MeasurementRow(Base):
    """Raw measurement; never rewritten after insert."""

    __tablename__ = "measurements"
    __table_args__ = (
        UniqueConstraint("sensor_id", "measured_at", name="uq_measurements_sensor_time"),
        Index("ix_measurements_point_time", "point_id", "measured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    sensor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sensors.id"))
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sensor_assignments.id"))
    point_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("points.id"))
    measured_at: Mapped[datetime] = mapped_column(Moment)
    received_at: Mapped[datetime] = mapped_column(Moment)
    temperature: Mapped[float | None] = mapped_column(Temperature)
    sensor_ok: Mapped[bool] = mapped_column(Boolean)
    source: Mapped[str] = mapped_column(String(20))
    humidity: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))
    rssi: Mapped[int | None] = mapped_column(SmallInteger)


class PointStateRow(Base):
    """Live monitoring state; updated only under ``SELECT … FOR UPDATE``."""

    __tablename__ = "point_states"

    point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("points.id", ondelete="CASCADE"), primary_key=True)
    last_measured_at: Mapped[datetime | None] = mapped_column(Moment)
    last_received_at: Mapped[datetime | None] = mapped_column(Moment)
    last_temperature: Mapped[float | None] = mapped_column(Temperature)
    last_sensor_ok: Mapped[bool | None] = mapped_column(Boolean)
    deviation_since: Mapped[datetime | None] = mapped_column(Moment)
    deviation_direction: Mapped[str | None] = mapped_column(String(10))
    normal_since: Mapped[datetime | None] = mapped_column(Moment)
    temperature_alarm: Mapped[str | None] = mapped_column(String(10))
    sensor_error: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    offline: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class IncidentRow(Base):
    """Incident; the partial unique index allows one open incident per point and type."""

    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "uq_incidents_open_per_type",
            "point_id",
            "type",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
        Index("ix_incidents_org_opened", "organization_id", "opened_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    point_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("points.id"))
    type: Mapped[str] = mapped_column(String(20))
    direction: Mapped[str | None] = mapped_column(String(10))
    opened_at: Mapped[datetime] = mapped_column(Moment)
    closed_at: Mapped[datetime | None] = mapped_column(Moment)
    open_temperature: Mapped[float | None] = mapped_column(Temperature)
    close_temperature: Mapped[float | None] = mapped_column(Temperature)


class RecipientRow(Base):
    """Telegram chat bound to an organization."""

    __tablename__ = "telegram_recipients"
    __table_args__ = (UniqueConstraint("organization_id", "chat_id", name="uq_recipients_org_chat"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(Moment)


class BindingCodeRow(Base):
    """One-time binding code (hash only)."""

    __tablename__ = "binding_codes"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    expires_at: Mapped[datetime] = mapped_column(Moment)
    used_at: Mapped[datetime | None] = mapped_column(Moment)


class NotificationEventRow(Base):
    """Notification about an incident, stored even without recipients."""

    __tablename__ = "notification_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(Moment)


class DeliveryRow(Base):
    """Delivery queue (outbox) entry: one event to one recipient."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        Index(
            "ix_deliveries_due",
            "next_attempt_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notification_events.id", ondelete="CASCADE"), index=True)
    recipient_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("telegram_recipients.id"))
    chat_id: Mapped[int] = mapped_column(BigInteger)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer)
    next_attempt_at: Mapped[datetime] = mapped_column(Moment)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(Moment)
