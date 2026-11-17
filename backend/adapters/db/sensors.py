"""Sensors and their time-bounded assignments."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.db.models import AssignmentRow, SensorRow
from backend.application.views import CurrentSensor
from backend.domain.sensors import Assignment, Sensor, SensorKind


def _sensor(row: SensorRow) -> Sensor:
    return Sensor(
        id=row.id,
        organization_id=row.organization_id,
        hardware_id=row.hardware_id,
        kind=SensorKind(row.kind),
        model=row.model,
        token_hash=row.token_hash,
        token_issued_at=row.token_issued_at,
        created_at=row.created_at,
    )


def _assignment(row: AssignmentRow) -> Assignment:
    return Assignment(
        id=row.id,
        sensor_id=row.sensor_id,
        point_id=row.point_id,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
    )


class SqlSensorRepository:
    """:class:`backend.application.ports.SensorRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, sensor: Sensor) -> None:
        """Insert."""
        self._session.add(
            SensorRow(
                id=sensor.id,
                organization_id=sensor.organization_id,
                hardware_id=sensor.hardware_id,
                kind=sensor.kind.value,
                model=sensor.model,
                token_hash=sensor.token_hash,
                token_issued_at=sensor.token_issued_at,
                created_at=sensor.created_at,
            ),
        )
        await self._session.flush()

    async def get(self, organization_id: UUID, sensor_id: UUID) -> Sensor | None:
        """A sensor of the organization."""
        row = await self._session.scalar(
            select(SensorRow).where(SensorRow.id == sensor_id, SensorRow.organization_id == organization_id),
        )
        return None if row is None else _sensor(row)

    async def for_organization(self, organization_id: UUID) -> list[Sensor]:
        """All sensors."""
        rows = await self._session.scalars(
            select(SensorRow).where(SensorRow.organization_id == organization_id).order_by(SensorRow.hardware_id),
        )
        return [_sensor(row) for row in rows]

    async def get_by_hardware_id(self, hardware_id: str) -> Sensor | None:
        """Global lookup."""
        row = await self._session.scalar(select(SensorRow).where(SensorRow.hardware_id == hardware_id))
        return None if row is None else _sensor(row)

    async def get_by_token_hash(self, token_hash: str) -> Sensor | None:
        """Device authentication."""
        row = await self._session.scalar(select(SensorRow).where(SensorRow.token_hash == token_hash))
        return None if row is None else _sensor(row)

    async def set_token(self, sensor_id: UUID, token_hash: str | None, moment: datetime) -> None:
        """Replace or revoke."""
        await self._session.execute(
            update(SensorRow).where(SensorRow.id == sensor_id).values(token_hash=token_hash, token_issued_at=moment),
        )


class SqlAssignmentRepository:
    """:class:`backend.application.ports.AssignmentRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, assignment: Assignment) -> None:
        """Insert; the EXCLUDE constraints reject overlaps."""
        self._session.add(
            AssignmentRow(
                id=assignment.id,
                sensor_id=assignment.sensor_id,
                point_id=assignment.point_id,
                starts_at=assignment.starts_at,
                ends_at=assignment.ends_at,
            ),
        )
        await self._session.flush()

    async def at(self, sensor_id: UUID, moment: datetime) -> Assignment | None:
        """Covering assignment."""
        row = await self._session.scalar(
            select(AssignmentRow).where(
                AssignmentRow.sensor_id == sensor_id,
                AssignmentRow.starts_at <= moment,
                or_(AssignmentRow.ends_at.is_(None), AssignmentRow.ends_at > moment),
            ),
        )
        return None if row is None else _assignment(row)

    async def open_for_sensor(self, sensor_id: UUID) -> Assignment | None:
        """Active assignment of a sensor."""
        row = await self._session.scalar(
            select(AssignmentRow).where(AssignmentRow.sensor_id == sensor_id, AssignmentRow.ends_at.is_(None)),
        )
        return None if row is None else _assignment(row)

    async def open_for_point(self, point_id: UUID) -> Assignment | None:
        """Active assignment of a point."""
        row = await self._session.scalar(
            select(AssignmentRow).where(AssignmentRow.point_id == point_id, AssignmentRow.ends_at.is_(None)),
        )
        return None if row is None else _assignment(row)

    async def close(self, assignment_id: UUID, ends_at: datetime) -> None:
        """End."""
        await self._session.execute(
            update(AssignmentRow).where(AssignmentRow.id == assignment_id).values(ends_at=ends_at)
        )
        await self._session.flush()

    async def for_sensor(self, sensor_id: UUID) -> list[Assignment]:
        """History, newest first."""
        rows = await self._session.scalars(
            select(AssignmentRow).where(AssignmentRow.sensor_id == sensor_id).order_by(AssignmentRow.starts_at.desc()),
        )
        return [_assignment(row) for row in rows]

    async def current_sensors(self, point_ids: Sequence[UUID]) -> dict[UUID, CurrentSensor]:
        """Active sensor per point."""
        if not point_ids:
            return {}
        result = await self._session.execute(
            select(AssignmentRow, SensorRow)
            .join(SensorRow, AssignmentRow.sensor_id == SensorRow.id)
            .where(AssignmentRow.point_id.in_(point_ids), AssignmentRow.ends_at.is_(None)),
        )
        return {
            assignment.point_id: CurrentSensor(
                sensor_id=sensor.id,
                hardware_id=sensor.hardware_id,
                kind=SensorKind(sensor.kind),
                since=assignment.starts_at,
            )
            for assignment, sensor in result.tuples()
        }
