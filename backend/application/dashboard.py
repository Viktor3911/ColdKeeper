"""Read-only queries for the overview, equipment card, chart and incidents screens."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from backend.application.ports import UnitOfWork, UnitOfWorkFactory
from backend.application.views import IncidentView, PointOverview, PointRecord, SeriesPoint
from backend.domain.equipment import Equipment
from backend.domain.errors import NotFoundError, ValidationFailedError
from backend.domain.monitoring import STATUS_SEVERITY, PointState
from backend.domain.organizations import Actor

MAX_SERIES_RANGE = timedelta(days=31)


class DashboardService:
    """Status data comes from stored point states; nothing is invented when data is missing."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def overview(self, actor: Actor, *, equipment_id: UUID | None = None) -> list[PointOverview]:
        """Points of the organization, the most severe status first."""
        async with self._uow_factory() as uow:
            records = await uow.inventory.point_records(actor.organization_id, equipment_id=equipment_id)
            points = await _overviews(uow, records)
        if equipment_id is None:
            points.sort(key=lambda point: -STATUS_SEVERITY[point.status])
        return points

    async def equipment_card(self, actor: Actor, equipment_id: UUID) -> tuple[Equipment, list[PointOverview]]:
        """Equipment with its points for the card."""
        async with self._uow_factory() as uow:
            equipment = await uow.inventory.get_equipment(actor.organization_id, equipment_id)
            if equipment is None:
                raise NotFoundError("Оборудование не найдено")
        return equipment, await self.overview(actor, equipment_id=equipment_id)

    async def series(self, actor: Actor, point_id: UUID, start: datetime, end: datetime) -> list[SeriesPoint]:
        """Chart data; failed probe readings are kept as gaps (``temperature=None``)."""
        if end <= start:
            raise ValidationFailedError("Конец периода должен быть позже начала")
        if end - start > MAX_SERIES_RANGE:
            raise ValidationFailedError("График — не больше 31 дня")
        async with self._uow_factory() as uow:
            if await uow.inventory.get_point(actor.organization_id, point_id) is None:
                raise NotFoundError("Точка измерения не найдена")
            return await uow.measurements.series(point_id, start, end)

    async def incidents(self, actor: Actor, *, only_open: bool, limit: int = 200) -> list[IncidentView]:
        """Incidents with their notification events."""
        async with self._uow_factory() as uow:
            incidents = await uow.incidents.recent(actor.organization_id, only_open=only_open, limit=limit)
            records = await uow.inventory.point_records(
                actor.organization_id,
                point_ids=list({incident.point_id for incident in incidents}),
            )
            locations = {record.location.point_id: record.location for record in records}
            events = await uow.notifications.events_for([incident.id for incident in incidents])
        return [
            IncidentView(incident=incident, location=locations[incident.point_id], events=events.get(incident.id, []))
            for incident in incidents
            if incident.point_id in locations
        ]


async def _overviews(uow: UnitOfWork, records: list[PointRecord]) -> list[PointOverview]:
    point_ids = [record.location.point_id for record in records]
    states = await uow.point_states.get_many(point_ids)
    sensors = await uow.assignments.current_sensors(point_ids)
    counts = await uow.incidents.open_counts(point_ids)
    result: list[PointOverview] = []
    for record in records:
        point_id = record.location.point_id
        state = states.get(point_id, PointState(point_id=point_id))
        result.append(
            PointOverview(
                record=record,
                state=state,
                status=state.status,
                sensor=sensors.get(point_id),
                open_incidents=counts.get(point_id, 0),
            ),
        )
    return result
