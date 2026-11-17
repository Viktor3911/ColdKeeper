"""Overview, equipment card, chart data and incidents."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from backend.interfaces.http.dependencies import ContainerDep, ReaderDep
from backend.interfaces.http.schemas import (
    EquipmentCardOut,
    EquipmentOut,
    IncidentOut,
    PointOverviewOut,
    SeriesPointOut,
)

router = APIRouter(prefix="/api/v1", tags=["monitoring"])


@router.get("/overview")
async def overview(container: ContainerDep, actor: ReaderDep) -> list[PointOverviewOut]:
    """All points, problems first."""
    return [PointOverviewOut.of(point) for point in await container.dashboard.overview(actor)]


@router.get("/equipment/{equipment_id}")
async def equipment_card(equipment_id: UUID, container: ContainerDep, actor: ReaderDep) -> EquipmentCardOut:
    """Equipment with its points and statuses."""
    equipment, points = await container.dashboard.equipment_card(actor, equipment_id)
    return EquipmentCardOut(
        equipment=EquipmentOut.of(equipment),
        points=[PointOverviewOut.of(point) for point in points],
    )


@router.get("/points/{point_id}/series")
async def series(
    point_id: UUID,
    container: ContainerDep,
    actor: ReaderDep,
    start: Annotated[datetime, Query(description="Начало, ISO 8601 с часовым поясом")],
    end: Annotated[datetime, Query(description="Конец (не включая), ISO 8601 с часовым поясом")],
) -> list[SeriesPointOut]:
    """Measurements for the chart."""
    if start.tzinfo is None or end.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Укажите часовой пояс в датах")
    points = await container.dashboard.series(actor, point_id, start.astimezone(UTC), end.astimezone(UTC))
    return [SeriesPointOut.of(point) for point in points]


@router.get("/incidents")
async def incidents(
    container: ContainerDep,
    actor: ReaderDep,
    only_open: Annotated[bool, Query(alias="open")] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[IncidentOut]:
    """Incidents, newest first, with their notifications."""
    views = await container.dashboard.incidents(actor, only_open=only_open, limit=limit)
    return [IncidentOut.of(view) for view in views]
