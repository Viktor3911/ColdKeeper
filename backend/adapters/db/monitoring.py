"""Point states (row-locked) and incidents."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.db.models import IncidentRow, PointRow, PointStateRow
from backend.domain.incidents import Incident
from backend.domain.monitoring import Direction, IncidentType, PointState


def _state(row: PointStateRow) -> PointState:
    return PointState(
        point_id=row.point_id,
        last_measured_at=row.last_measured_at,
        last_received_at=row.last_received_at,
        last_temperature=row.last_temperature,
        last_sensor_ok=row.last_sensor_ok,
        deviation_since=row.deviation_since,
        deviation_direction=None if row.deviation_direction is None else Direction(row.deviation_direction),
        normal_since=row.normal_since,
        temperature_alarm=None if row.temperature_alarm is None else Direction(row.temperature_alarm),
        sensor_error=row.sensor_error,
        offline=row.offline,
    )


def _incident(row: IncidentRow) -> Incident:
    return Incident(
        id=row.id,
        organization_id=row.organization_id,
        point_id=row.point_id,
        type=IncidentType(row.type),
        direction=None if row.direction is None else Direction(row.direction),
        opened_at=row.opened_at,
        closed_at=row.closed_at,
        open_temperature=row.open_temperature,
        close_temperature=row.close_temperature,
    )


class SqlPointStateRepository:
    """:class:`backend.application.ports.PointStateRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock(self, point_id: UUID) -> PointState:
        """Create the row if needed, then ``SELECT … FOR UPDATE``."""
        await self._session.execute(insert(PointStateRow).values(point_id=point_id).on_conflict_do_nothing())
        row = await self._session.scalar(
            select(PointStateRow)
            .where(PointStateRow.point_id == point_id)
            .with_for_update()
            .execution_options(populate_existing=True),
        )
        if row is None:  # pragma: no cover - the point was deleted concurrently
            return PointState(point_id=point_id)
        return _state(row)

    async def save(self, state: PointState) -> None:
        """Write all fields."""
        await self._session.execute(
            update(PointStateRow)
            .where(PointStateRow.point_id == state.point_id)
            .values(
                last_measured_at=state.last_measured_at,
                last_received_at=state.last_received_at,
                last_temperature=state.last_temperature,
                last_sensor_ok=state.last_sensor_ok,
                deviation_since=state.deviation_since,
                deviation_direction=None if state.deviation_direction is None else state.deviation_direction.value,
                normal_since=state.normal_since,
                temperature_alarm=None if state.temperature_alarm is None else state.temperature_alarm.value,
                sensor_error=state.sensor_error,
                offline=state.offline,
            ),
        )

    async def get_many(self, point_ids: Sequence[UUID]) -> dict[UUID, PointState]:
        """Plain read."""
        if not point_ids:
            return {}
        rows = await self._session.scalars(select(PointStateRow).where(PointStateRow.point_id.in_(point_ids)))
        return {row.point_id: _state(row) for row in rows}

    async def silent_candidates(self, now: datetime, limit: int) -> list[UUID]:
        """Last contact older than the point's own offline timeout."""
        deadline = PointStateRow.last_received_at + func.make_interval(
            0, 0, 0, 0, 0, 0, PointRow.offline_timeout_seconds
        )
        rows = await self._session.scalars(
            select(PointStateRow.point_id)
            .join(PointRow, PointRow.id == PointStateRow.point_id)
            .where(
                PointStateRow.offline.is_(False),
                PointStateRow.last_received_at.is_not(None),
                deadline < now,
            )
            .limit(limit),
        )
        return list(rows)


class SqlIncidentRepository:
    """:class:`backend.application.ports.IncidentRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def open(self, incident: Incident) -> bool:
        """Insert unless an incident of this type is already open (partial unique index)."""
        statement = (
            insert(IncidentRow)
            .values(
                id=incident.id,
                organization_id=incident.organization_id,
                point_id=incident.point_id,
                type=incident.type.value,
                direction=None if incident.direction is None else incident.direction.value,
                opened_at=incident.opened_at,
                closed_at=None,
                open_temperature=incident.open_temperature,
                close_temperature=None,
            )
            .on_conflict_do_nothing(index_elements=["point_id", "type"], index_where=IncidentRow.closed_at.is_(None))
            .returning(IncidentRow.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def get_open(self, point_id: UUID, incident_type: IncidentType) -> Incident | None:
        """Open incident of a type."""
        row = await self._session.scalar(
            select(IncidentRow).where(
                IncidentRow.point_id == point_id,
                IncidentRow.type == incident_type.value,
                IncidentRow.closed_at.is_(None),
            ),
        )
        return None if row is None else _incident(row)

    async def close(self, incident_id: UUID, closed_at: datetime, temperature: float | None) -> None:
        """Close."""
        await self._session.execute(
            update(IncidentRow)
            .where(IncidentRow.id == incident_id)
            .values(closed_at=closed_at, close_temperature=temperature),
        )

    async def recent(self, organization_id: UUID, *, only_open: bool, limit: int) -> list[Incident]:
        """Newest first."""
        query = select(IncidentRow).where(IncidentRow.organization_id == organization_id)
        if only_open:
            query = query.where(IncidentRow.closed_at.is_(None))
        rows = await self._session.scalars(query.order_by(IncidentRow.opened_at.desc()).limit(limit))
        return [_incident(row) for row in rows]

    async def open_counts(self, point_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Open incidents per point."""
        if not point_ids:
            return {}
        result = await self._session.execute(
            select(IncidentRow.point_id, func.count())
            .where(IncidentRow.point_id.in_(point_ids), IncidentRow.closed_at.is_(None))
            .group_by(IncidentRow.point_id),
        )
        return dict(result.tuples().all())
