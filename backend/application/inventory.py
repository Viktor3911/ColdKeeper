"""Sites, rooms, equipment and measurement points of the actor's organization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import time, timedelta
from uuid import UUID

from backend.application.ports import InventoryKind, UnitOfWork, UnitOfWorkFactory
from backend.application.views import SitesTree
from backend.domain.equipment import (
    Equipment,
    EquipmentKind,
    MeasurementPoint,
    PointSettings,
    Room,
    Site,
    check_timezone,
    clean_name,
)
from backend.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from backend.domain.organizations import Actor

MAX_CONTROL_WINDOW = timedelta(hours=6)


@dataclass(frozen=True, slots=True)
class SiteInput:
    """Editable fields of a site."""

    name: str
    address: str
    timezone: str
    control_time: time
    control_window: timedelta


class InventoryService:
    """CRUD with organization checks on every call; deleting is allowed only for empty entities."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def tree(self, actor: Actor) -> SitesTree:
        """Everything for the inventory screen."""
        org = actor.organization_id
        async with self._uow_factory() as uow:
            return SitesTree(
                sites=await uow.inventory.sites(org),
                rooms=await uow.inventory.rooms(org),
                equipment=await uow.inventory.equipment(org),
                points=await uow.inventory.points(org),
            )

    async def save_site(self, actor: Actor, data: SiteInput, site_id: UUID | None = None) -> Site:
        """Create or update a site."""
        actor.require_owner()
        if not timedelta(minutes=1) <= data.control_window <= MAX_CONTROL_WINDOW:
            raise ValidationFailedError("Окно контрольного измерения — от 1 минуты до 6 часов")
        site = Site(
            id=site_id or uuid.uuid4(),
            organization_id=actor.organization_id,
            name=clean_name(data.name, "название объекта"),
            address=data.address.strip(),
            timezone=check_timezone(data.timezone.strip()),
            control_time=data.control_time.replace(second=0, microsecond=0, tzinfo=None),
            control_window=data.control_window,
        )
        async with self._uow_factory() as uow:
            if site_id is not None:
                await self._site(uow, actor, site_id)
            await uow.inventory.save_site(actor.organization_id, site)
            await uow.commit()
        return site

    async def save_room(self, actor: Actor, site_id: UUID, name: str, room_id: UUID | None = None) -> Room:
        """Create or update a room."""
        actor.require_owner()
        room = Room(id=room_id or uuid.uuid4(), site_id=site_id, name=clean_name(name, "название помещения"))
        async with self._uow_factory() as uow:
            await self._site(uow, actor, site_id)
            if room_id is not None:
                await self._room(uow, actor, room_id)
            await uow.inventory.save_room(room)
            await uow.commit()
        return room

    async def save_equipment(
        self,
        actor: Actor,
        room_id: UUID,
        name: str,
        kind: EquipmentKind,
        equipment_id: UUID | None = None,
    ) -> Equipment:
        """Create or update equipment."""
        actor.require_owner()
        equipment = Equipment(
            id=equipment_id or uuid.uuid4(),
            room_id=room_id,
            name=clean_name(name, "название оборудования"),
            kind=kind,
        )
        async with self._uow_factory() as uow:
            await self._room(uow, actor, room_id)
            if equipment_id is not None:
                await self._equipment(uow, actor, equipment_id)
            await uow.inventory.save_equipment(equipment)
            await uow.commit()
        return equipment

    async def save_point(
        self,
        actor: Actor,
        equipment_id: UUID,
        name: str,
        settings: PointSettings,
        point_id: UUID | None = None,
    ) -> MeasurementPoint:
        """Create a point or change its name and monitoring settings."""
        actor.require_owner()
        point = MeasurementPoint(
            id=point_id or uuid.uuid4(),
            equipment_id=equipment_id,
            name=clean_name(name, "название точки"),
            settings=settings,
        )
        async with self._uow_factory() as uow:
            await self._equipment(uow, actor, equipment_id)
            if point_id is not None:
                await self._point(uow, actor, point_id)
            await uow.inventory.save_point(point)
            await uow.commit()
        return point

    async def delete(self, actor: Actor, kind: InventoryKind, entity_id: UUID) -> None:
        """Delete an entity that has no rooms, equipment, points, sensors or measurements below it."""
        actor.require_owner()
        async with self._uow_factory() as uow:
            await self._check_exists(uow, actor, kind, entity_id)
            if await uow.inventory.has_children(kind, entity_id):
                raise ConflictError("Нельзя удалить: есть вложенные элементы, привязки датчиков или история измерений")
            await uow.inventory.delete(kind, entity_id)
            await uow.commit()

    async def _check_exists(self, uow: UnitOfWork, actor: Actor, kind: InventoryKind, entity_id: UUID) -> None:
        match kind:
            case InventoryKind.SITE:
                await self._site(uow, actor, entity_id)
            case InventoryKind.ROOM:
                await self._room(uow, actor, entity_id)
            case InventoryKind.EQUIPMENT:
                await self._equipment(uow, actor, entity_id)
            case InventoryKind.POINT:
                await self._point(uow, actor, entity_id)

    @staticmethod
    async def _site(uow: UnitOfWork, actor: Actor, site_id: UUID) -> Site:
        site = await uow.inventory.get_site(actor.organization_id, site_id)
        if site is None:
            raise NotFoundError("Объект не найден")
        return site

    @staticmethod
    async def _room(uow: UnitOfWork, actor: Actor, room_id: UUID) -> Room:
        room = await uow.inventory.get_room(actor.organization_id, room_id)
        if room is None:
            raise NotFoundError("Помещение не найдено")
        return room

    @staticmethod
    async def _equipment(uow: UnitOfWork, actor: Actor, equipment_id: UUID) -> Equipment:
        equipment = await uow.inventory.get_equipment(actor.organization_id, equipment_id)
        if equipment is None:
            raise NotFoundError("Оборудование не найдено")
        return equipment

    @staticmethod
    async def _point(uow: UnitOfWork, actor: Actor, point_id: UUID) -> MeasurementPoint:
        point = await uow.inventory.get_point(actor.organization_id, point_id)
        if point is None:
            raise NotFoundError("Точка измерения не найдена")
        return point
