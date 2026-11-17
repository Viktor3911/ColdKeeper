"""Initial schema: organizations, inventory, sensors, measurements, monitoring, notifications.

Revision ID: 0001
Revises:
Create Date: 2026-11-03
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MOMENT = sa.DateTime(timezone=True)
TEMPERATURE = sa.Numeric(6, 2, asdecimal=False)


def _id() -> sa.Column[uuid.UUID]:
    return sa.Column("id", sa.Uuid(), nullable=False)


def upgrade() -> None:
    """Create all tables."""
    # btree_gist lets one GiST EXCLUDE constraint combine "same sensor" (=) with "overlapping period" (&&).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "organizations",
        _id(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("created_at", MOMENT, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organizations"),
        sa.UniqueConstraint("name", name="uq_organizations_name"),
    )
    op.create_table(
        "users",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("login", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", MOMENT, nullable=False),
        sa.CheckConstraint("role IN ('owner', 'observer')", name="ck_users_role"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name="fk_users_organization_id_organizations"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("login", name="uq_users_login"),
    )
    op.create_index("ix_users_organization_id", "users", ["organization_id"])
    op.create_table(
        "sessions",
        sa.Column("id_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("csrf_token", sa.String(100), nullable=False),
        sa.Column("created_at", MOMENT, nullable=False),
        sa.Column("last_seen_at", MOMENT, nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id_hash", name="pk_sessions"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "login_attempts",
        sa.Column("login", sa.String(100), nullable=False),
        sa.Column("address", sa.String(64), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("locked_until", MOMENT, nullable=True),
        sa.Column("updated_at", MOMENT, nullable=False),
        sa.PrimaryKeyConstraint("login", "address", name="pk_login_attempts"),
    )

    op.create_table(
        "sites",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("control_time", sa.Time(), nullable=False),
        sa.Column("control_window_minutes", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name="fk_sites_organization_id_organizations"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sites"),
    )
    op.create_index("ix_sites_organization_id", "sites", ["organization_id"])
    op.create_table(
        "rooms",
        _id(),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name="fk_rooms_site_id_sites"),
        sa.PrimaryKeyConstraint("id", name="pk_rooms"),
    )
    op.create_index("ix_rooms_site_id", "rooms", ["site_id"])
    op.create_table(
        "equipment",
        _id(),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_equipment_room_id_rooms"),
        sa.PrimaryKeyConstraint("id", name="pk_equipment"),
    )
    op.create_index("ix_equipment_room_id", "equipment", ["room_id"])
    op.create_table(
        "points",
        _id(),
        sa.Column("equipment_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("low_threshold", TEMPERATURE, nullable=False),
        sa.Column("high_threshold", TEMPERATURE, nullable=False),
        sa.Column("deviation_seconds", sa.Integer(), nullable=False),
        sa.Column("recovery_seconds", sa.Integer(), nullable=False),
        sa.Column("expected_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("offline_timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("profile", sa.String(20), nullable=False),
        sa.CheckConstraint("low_threshold < high_threshold", name="ck_points_threshold_order"),
        sa.ForeignKeyConstraint(["equipment_id"], ["equipment.id"], name="fk_points_equipment_id_equipment"),
        sa.PrimaryKeyConstraint("id", name="pk_points"),
    )
    op.create_index("ix_points_equipment_id", "points", ["equipment_id"])

    op.create_table(
        "sensors",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("hardware_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("token_issued_at", MOMENT, nullable=True),
        sa.Column("created_at", MOMENT, nullable=False),
        sa.CheckConstraint("kind IN ('physical', 'simulated')", name="ck_sensors_kind"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name="fk_sensors_organization_id_organizations"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sensors"),
        sa.UniqueConstraint("hardware_id", name="uq_sensors_hardware_id"),
        sa.UniqueConstraint("token_hash", name="uq_sensors_token_hash"),
    )
    op.create_index("ix_sensors_organization_id", "sensors", ["organization_id"])
    op.create_table(
        "sensor_assignments",
        _id(),
        sa.Column("sensor_id", sa.Uuid(), nullable=False),
        sa.Column("point_id", sa.Uuid(), nullable=False),
        sa.Column("starts_at", MOMENT, nullable=False),
        sa.Column("ends_at", MOMENT, nullable=True),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_sensor_assignments_period"),
        sa.ForeignKeyConstraint(["point_id"], ["points.id"], name="fk_sensor_assignments_point_id_points"),
        sa.ForeignKeyConstraint(["sensor_id"], ["sensors.id"], name="fk_sensor_assignments_sensor_id_sensors"),
        sa.PrimaryKeyConstraint("id", name="pk_sensor_assignments"),
    )
    op.create_index("ix_sensor_assignments_sensor_id", "sensor_assignments", ["sensor_id"])
    op.create_index("ix_sensor_assignments_point_id", "sensor_assignments", ["point_id"])
    # A sensor measures one point at a time, and a point has one sensor at a time ([start, end) periods).
    op.execute(
        "ALTER TABLE sensor_assignments ADD CONSTRAINT ex_sensor_assignments_sensor_overlap "
        "EXCLUDE USING gist (sensor_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)",
    )
    op.execute(
        "ALTER TABLE sensor_assignments ADD CONSTRAINT ex_sensor_assignments_point_overlap "
        "EXCLUDE USING gist (point_id WITH =, tstzrange(starts_at, ends_at, '[)') WITH &&)",
    )

    op.create_table(
        "measurements",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("sensor_id", sa.Uuid(), nullable=False),
        sa.Column("assignment_id", sa.Uuid(), nullable=True),
        sa.Column("point_id", sa.Uuid(), nullable=True),
        sa.Column("measured_at", MOMENT, nullable=False),
        sa.Column("received_at", MOMENT, nullable=False),
        sa.Column("temperature", TEMPERATURE, nullable=True),
        sa.Column("sensor_ok", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("humidity", sa.Numeric(5, 2, asdecimal=False), nullable=True),
        sa.Column("rssi", sa.SmallInteger(), nullable=True),
        # A failed probe has no temperature; a working probe always has one (never 0 °C as a placeholder).
        sa.CheckConstraint("sensor_ok = (temperature IS NOT NULL)", name="ck_measurements_ok_temperature"),
        sa.CheckConstraint("source IN ('device', 'simulator')", name="ck_measurements_source"),
        sa.CheckConstraint("(point_id IS NULL) = (assignment_id IS NULL)", name="ck_measurements_assignment"),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["sensor_assignments.id"],
            name="fk_measurements_assignment_id_sensor_assignments",
        ),
        sa.ForeignKeyConstraint(["point_id"], ["points.id"], name="fk_measurements_point_id_points"),
        sa.ForeignKeyConstraint(["sensor_id"], ["sensors.id"], name="fk_measurements_sensor_id_sensors"),
        sa.PrimaryKeyConstraint("id", name="pk_measurements"),
        sa.UniqueConstraint("sensor_id", "measured_at", name="uq_measurements_sensor_time"),
    )
    op.create_index("ix_measurements_point_time", "measurements", ["point_id", "measured_at"])

    op.create_table(
        "point_states",
        sa.Column("point_id", sa.Uuid(), nullable=False),
        sa.Column("last_measured_at", MOMENT, nullable=True),
        sa.Column("last_received_at", MOMENT, nullable=True),
        sa.Column("last_temperature", TEMPERATURE, nullable=True),
        sa.Column("last_sensor_ok", sa.Boolean(), nullable=True),
        sa.Column("deviation_since", MOMENT, nullable=True),
        sa.Column("deviation_direction", sa.String(10), nullable=True),
        sa.Column("normal_since", MOMENT, nullable=True),
        sa.Column("temperature_alarm", sa.String(10), nullable=True),
        sa.Column("sensor_error", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("offline", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["point_id"], ["points.id"], name="fk_point_states_point_id_points", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("point_id", name="pk_point_states"),
    )
    op.create_table(
        "incidents",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("point_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("direction", sa.String(10), nullable=True),
        sa.Column("opened_at", MOMENT, nullable=False),
        sa.Column("closed_at", MOMENT, nullable=True),
        sa.Column("open_temperature", TEMPERATURE, nullable=True),
        sa.Column("close_temperature", TEMPERATURE, nullable=True),
        sa.CheckConstraint("type IN ('temperature', 'sensor_error', 'connection_lost')", name="ck_incidents_type"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["organizations.id"], name="fk_incidents_organization_id_organizations"
        ),
        sa.ForeignKeyConstraint(["point_id"], ["points.id"], name="fk_incidents_point_id_points"),
        sa.PrimaryKeyConstraint("id", name="pk_incidents"),
    )
    op.create_index(
        "uq_incidents_open_per_type",
        "incidents",
        ["point_id", "type"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_index("ix_incidents_org_opened", "incidents", ["organization_id", "opened_at"])

    op.create_table(
        "telegram_recipients",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", MOMENT, nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_telegram_recipients_organization_id_organizations",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_telegram_recipients"),
        sa.UniqueConstraint("organization_id", "chat_id", name="uq_recipients_org_chat"),
    )
    op.create_table(
        "binding_codes",
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", MOMENT, nullable=False),
        sa.Column("used_at", MOMENT, nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_binding_codes_organization_id_organizations",
        ),
        sa.PrimaryKeyConstraint("code_hash", name="pk_binding_codes"),
    )
    op.create_index("ix_binding_codes_organization_id", "binding_codes", ["organization_id"])
    op.create_table(
        "notification_events",
        _id(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", MOMENT, nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], name="fk_notification_events_incident_id_incidents"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_notification_events_organization_id_organizations",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_events"),
    )
    op.create_index("ix_notification_events_incident_id", "notification_events", ["incident_id"])
    op.create_table(
        "notification_deliveries",
        _id(),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", MOMENT, nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", MOMENT, nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed', 'dry_run')",
            name="ck_notification_deliveries_status",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["notification_events.id"],
            name="fk_notification_deliveries_event_id_notification_events",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["telegram_recipients.id"],
            name="fk_notification_deliveries_recipient_id_telegram_recipients",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_deliveries"),
    )
    op.create_index("ix_notification_deliveries_event_id", "notification_deliveries", ["event_id"])
    op.create_index(
        "ix_deliveries_due",
        "notification_deliveries",
        ["next_attempt_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    """Drop all tables (the btree_gist extension is left in place: other objects may use it)."""
    for table in (
        "notification_deliveries",
        "notification_events",
        "binding_codes",
        "telegram_recipients",
        "incidents",
        "point_states",
        "measurements",
        "sensor_assignments",
        "sensors",
        "points",
        "equipment",
        "rooms",
        "sites",
        "login_attempts",
        "sessions",
        "users",
        "organizations",
    ):
        op.drop_table(table)
