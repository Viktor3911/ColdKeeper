"""Sensors, device tokens and assignments."""

from __future__ import annotations

from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Response, status

from backend.application.views import IssuedToken
from backend.composition import Container
from backend.interfaces.http.dependencies import ContainerDep, ReaderDep, WriterDep
from backend.interfaces.http.schemas import (
    AssignmentIn,
    AssignmentOut,
    SensorDetailOut,
    SensorIn,
    SensorOut,
    TokenOut,
)

router = APIRouter(prefix="/api/v1/sensors", tags=["sensors"])


def ingest_url(container: Container) -> str:
    """URL template for the device's HTTP push settings (the token is filled in by the owner)."""
    return container.settings.public_url.rstrip("/") + "/api/v1/ingest/unitx?token="


def _token(container: Container, issued: IssuedToken) -> TokenOut:
    return TokenOut(sensor_id=issued.sensor_id, token=issued.token, ingest_url=ingest_url(container) + issued.token)


@router.get("")
async def list_sensors(container: ContainerDep, actor: ReaderDep) -> list[SensorOut]:
    """Sensors of the organization."""
    return [SensorOut.of(view) for view in await container.sensors.list_sensors(actor)]


@router.get("/{sensor_id}")
async def sensor_detail(sensor_id: UUID, container: ContainerDep, actor: ReaderDep) -> SensorDetailOut:
    """Sensor with assignment history."""
    view, history = await container.sensors.get(actor, sensor_id)
    return SensorDetailOut(sensor=SensorOut.of(view), history=[AssignmentOut.of(item) for item in history])


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_sensor(body: SensorIn, container: ContainerDep, actor: WriterDep) -> TokenOut:
    """Register a sensor; the token is shown only in this response."""
    return _token(container, await container.sensors.register(actor, body.hardware_id, body.kind, body.model))


@router.post("/{sensor_id}/token")
async def reissue_token(sensor_id: UUID, container: ContainerDep, actor: WriterDep) -> TokenOut:
    """New token; the old one stops working."""
    return _token(container, await container.sensors.issue_token(actor, sensor_id))


@router.delete("/{sensor_id}/token", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_token(sensor_id: UUID, container: ContainerDep, actor: WriterDep) -> Response:
    """Revoke the token."""
    await container.sensors.revoke_token(actor, sensor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{sensor_id}/assignment", status_code=status.HTTP_201_CREATED)
async def assign(sensor_id: UUID, body: AssignmentIn, container: ContainerDep, actor: WriterDep) -> AssignmentOut:
    """Assign to a point (replacing the point's previous sensor at the same moment)."""
    starts_at = None if body.starts_at is None else body.starts_at.astimezone(UTC)
    return AssignmentOut.of(await container.sensors.assign(actor, sensor_id, body.point_id, starts_at))


@router.delete("/{sensor_id}/assignment", status_code=status.HTTP_204_NO_CONTENT)
async def unassign(sensor_id: UUID, container: ContainerDep, actor: WriterDep) -> Response:
    """End the current assignment."""
    await container.sensors.unassign(actor, sensor_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
