"""Sites, rooms, equipment and measurement points."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Response, status

from backend.application.inventory import SiteInput
from backend.application.ports import InventoryKind
from backend.domain.equipment import PointSettings
from backend.interfaces.http.dependencies import ContainerDep, ReaderDep, WriterDep
from backend.interfaces.http.schemas import (
    EquipmentIn,
    EquipmentOut,
    InventoryOut,
    PointIn,
    PointOut,
    PointSettingsBody,
    RoomIn,
    RoomOut,
    SiteIn,
    SiteOut,
)

router = APIRouter(prefix="/api/v1", tags=["inventory"])


def _settings(body: PointSettingsBody) -> PointSettings:
    return PointSettings(
        low_threshold=body.low_threshold,
        high_threshold=body.high_threshold,
        deviation_duration=timedelta(seconds=body.deviation_seconds),
        recovery_duration=timedelta(seconds=body.recovery_seconds),
        expected_interval=timedelta(seconds=body.expected_interval_seconds),
        offline_timeout=timedelta(seconds=body.offline_timeout_seconds),
        profile=body.profile,
    )


def _site_input(body: SiteIn) -> SiteInput:
    return SiteInput(
        name=body.name,
        address=body.address,
        timezone=body.timezone,
        control_time=body.control_time,
        control_window=timedelta(minutes=body.control_window_minutes),
    )


@router.get("/inventory")
async def inventory(container: ContainerDep, actor: ReaderDep) -> InventoryOut:
    """All sites, rooms, equipment and points of the organization."""
    tree = await container.inventory.tree(actor)
    return InventoryOut(
        sites=[SiteOut.of(site) for site in tree.sites],
        rooms=[RoomOut.of(room) for room in tree.rooms],
        equipment=[EquipmentOut.of(item) for item in tree.equipment],
        points=[PointOut.of(point) for point in tree.points],
    )


@router.post("/sites", status_code=status.HTTP_201_CREATED)
async def create_site(body: SiteIn, container: ContainerDep, actor: WriterDep) -> SiteOut:
    """New site."""
    return SiteOut.of(await container.inventory.save_site(actor, _site_input(body)))


@router.put("/sites/{site_id}")
async def update_site(site_id: UUID, body: SiteIn, container: ContainerDep, actor: WriterDep) -> SiteOut:
    """Edit a site."""
    return SiteOut.of(await container.inventory.save_site(actor, _site_input(body), site_id))


@router.post("/rooms", status_code=status.HTTP_201_CREATED)
async def create_room(body: RoomIn, container: ContainerDep, actor: WriterDep) -> RoomOut:
    """New room."""
    return RoomOut.of(await container.inventory.save_room(actor, body.site_id, body.name))


@router.put("/rooms/{room_id}")
async def update_room(room_id: UUID, body: RoomIn, container: ContainerDep, actor: WriterDep) -> RoomOut:
    """Edit a room."""
    return RoomOut.of(await container.inventory.save_room(actor, body.site_id, body.name, room_id))


@router.post("/equipment", status_code=status.HTTP_201_CREATED)
async def create_equipment(body: EquipmentIn, container: ContainerDep, actor: WriterDep) -> EquipmentOut:
    """New equipment."""
    return EquipmentOut.of(await container.inventory.save_equipment(actor, body.room_id, body.name, body.kind))


@router.put("/equipment/{equipment_id}")
async def update_equipment(
    equipment_id: UUID,
    body: EquipmentIn,
    container: ContainerDep,
    actor: WriterDep,
) -> EquipmentOut:
    """Edit equipment."""
    equipment = await container.inventory.save_equipment(actor, body.room_id, body.name, body.kind, equipment_id)
    return EquipmentOut.of(equipment)


@router.post("/points", status_code=status.HTTP_201_CREATED)
async def create_point(body: PointIn, container: ContainerDep, actor: WriterDep) -> PointOut:
    """New measurement point."""
    point = await container.inventory.save_point(actor, body.equipment_id, body.name, _settings(body.settings))
    return PointOut.of(point)


@router.put("/points/{point_id}")
async def update_point(point_id: UUID, body: PointIn, container: ContainerDep, actor: WriterDep) -> PointOut:
    """Edit a point and its monitoring settings."""
    point = await container.inventory.save_point(
        actor, body.equipment_id, body.name, _settings(body.settings), point_id
    )
    return PointOut.of(point)


async def _delete(container: ContainerDep, actor: WriterDep, kind: InventoryKind, entity_id: UUID) -> Response:
    await container.inventory.delete(actor, kind, entity_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/sites/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(site_id: UUID, container: ContainerDep, actor: WriterDep) -> Response:
    """Delete a site without rooms."""
    return await _delete(container, actor, InventoryKind.SITE, site_id)


@router.delete("/rooms/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(room_id: UUID, container: ContainerDep, actor: WriterDep) -> Response:
    """Delete a room without equipment."""
    return await _delete(container, actor, InventoryKind.ROOM, room_id)


@router.delete("/equipment/{equipment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_equipment(equipment_id: UUID, container: ContainerDep, actor: WriterDep) -> Response:
    """Delete equipment without points."""
    return await _delete(container, actor, InventoryKind.EQUIPMENT, equipment_id)


@router.delete("/points/{point_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_point(point_id: UUID, container: ContainerDep, actor: WriterDep) -> Response:
    """Delete a point that never had a sensor or measurements."""
    return await _delete(container, actor, InventoryKind.POINT, point_id)
