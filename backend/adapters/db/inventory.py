"""Sites, rooms, equipment and points; every user-facing query joins up to the organization."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Select, delete, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.db.models import (
    AssignmentRow,
    EquipmentRow,
    MeasurementRow,
    OrganizationRow,
    PointRow,
    RoomRow,
    SiteRow,
)
from backend.application.ports import InventoryKind
from backend.application.views import PointRecord
from backend.domain.equipment import (
    Equipment,
    EquipmentKind,
    MeasurementPoint,
    PointLocation,
    PointSettings,
    Room,
    SettingsProfile,
    Site,
)


def site_from_row(row: SiteRow) -> Site:
    """ORM → domain."""
    return Site(
        id=row.id,
        organization_id=row.organization_id,
        name=row.name,
        address=row.address,
        timezone=row.timezone,
        control_time=row.control_time,
        control_window=timedelta(minutes=row.control_window_minutes),
    )


def settings_from_row(row: PointRow) -> PointSettings:
    """ORM → domain settings."""
    return PointSettings(
        low_threshold=row.low_threshold,
        high_threshold=row.high_threshold,
        deviation_duration=timedelta(seconds=row.deviation_seconds),
        recovery_duration=timedelta(seconds=row.recovery_seconds),
        expected_interval=timedelta(seconds=row.expected_interval_seconds),
        offline_timeout=timedelta(seconds=row.offline_timeout_seconds),
        profile=SettingsProfile(row.profile),
    )


def _point(row: PointRow) -> MeasurementPoint:
    return MeasurementPoint(id=row.id, equipment_id=row.equipment_id, name=row.name, settings=settings_from_row(row))


def _location(
    point: PointRow,
    equipment: EquipmentRow,
    room: RoomRow,
    site: SiteRow,
    organization: OrganizationRow,
) -> PointLocation:
    return PointLocation(
        organization_id=organization.id,
        organization_name=organization.name,
        site_id=site.id,
        site_name=site.name,
        timezone=site.timezone,
        room_id=room.id,
        room_name=room.name,
        equipment_id=equipment.id,
        equipment_name=equipment.name,
        point_id=point.id,
        point_name=point.name,
    )


def location_query() -> Select[tuple[PointRow, EquipmentRow, RoomRow, SiteRow, OrganizationRow]]:
    """Point with its full path, ordered for journals and lists."""
    return (
        select(PointRow, EquipmentRow, RoomRow, SiteRow, OrganizationRow)
        .join(EquipmentRow, PointRow.equipment_id == EquipmentRow.id)
        .join(RoomRow, EquipmentRow.room_id == RoomRow.id)
        .join(SiteRow, RoomRow.site_id == SiteRow.id)
        .join(OrganizationRow, SiteRow.organization_id == OrganizationRow.id)
        .order_by(SiteRow.name, RoomRow.name, EquipmentRow.name, PointRow.name)
    )


def record_from(row: Any) -> PointRecord:
    """Tuple from :func:`location_query` → record."""
    point, equipment, room, site, organization = row
    return PointRecord(
        location=_location(point, equipment, room, site, organization), settings=settings_from_row(point)
    )


class SqlInventoryRepository:
    """:class:`backend.application.ports.InventoryRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def sites(self, organization_id: UUID) -> list[Site]:
        """All sites."""
        rows = await self._session.scalars(
            select(SiteRow).where(SiteRow.organization_id == organization_id).order_by(SiteRow.name),
        )
        return [site_from_row(row) for row in rows]

    async def rooms(self, organization_id: UUID) -> list[Room]:
        """All rooms."""
        rows = await self._session.scalars(
            select(RoomRow)
            .join(SiteRow, RoomRow.site_id == SiteRow.id)
            .where(SiteRow.organization_id == organization_id)
            .order_by(RoomRow.name),
        )
        return [Room(id=row.id, site_id=row.site_id, name=row.name) for row in rows]

    async def equipment(self, organization_id: UUID) -> list[Equipment]:
        """All equipment."""
        rows = await self._session.scalars(
            select(EquipmentRow)
            .join(RoomRow, EquipmentRow.room_id == RoomRow.id)
            .join(SiteRow, RoomRow.site_id == SiteRow.id)
            .where(SiteRow.organization_id == organization_id)
            .order_by(EquipmentRow.name),
        )
        return [Equipment(id=row.id, room_id=row.room_id, name=row.name, kind=EquipmentKind(row.kind)) for row in rows]

    async def points(self, organization_id: UUID) -> list[MeasurementPoint]:
        """All points."""
        rows = await self._session.scalars(
            select(PointRow)
            .join(EquipmentRow, PointRow.equipment_id == EquipmentRow.id)
            .join(RoomRow, EquipmentRow.room_id == RoomRow.id)
            .join(SiteRow, RoomRow.site_id == SiteRow.id)
            .where(SiteRow.organization_id == organization_id)
            .order_by(PointRow.name),
        )
        return [_point(row) for row in rows]

    async def get_site(self, organization_id: UUID, site_id: UUID) -> Site | None:
        """A site of the organization."""
        row = await self._session.scalar(
            select(SiteRow).where(SiteRow.id == site_id, SiteRow.organization_id == organization_id),
        )
        return None if row is None else site_from_row(row)

    async def get_room(self, organization_id: UUID, room_id: UUID) -> Room | None:
        """A room of the organization."""
        row = await self._session.scalar(
            select(RoomRow)
            .join(SiteRow, RoomRow.site_id == SiteRow.id)
            .where(RoomRow.id == room_id, SiteRow.organization_id == organization_id),
        )
        return None if row is None else Room(id=row.id, site_id=row.site_id, name=row.name)

    async def get_equipment(self, organization_id: UUID, equipment_id: UUID) -> Equipment | None:
        """Equipment of the organization."""
        row = await self._session.scalar(
            select(EquipmentRow)
            .join(RoomRow, EquipmentRow.room_id == RoomRow.id)
            .join(SiteRow, RoomRow.site_id == SiteRow.id)
            .where(EquipmentRow.id == equipment_id, SiteRow.organization_id == organization_id),
        )
        return (
            None
            if row is None
            else Equipment(id=row.id, room_id=row.room_id, name=row.name, kind=EquipmentKind(row.kind))
        )

    async def get_point(self, organization_id: UUID, point_id: UUID) -> MeasurementPoint | None:
        """A point of the organization."""
        row = await self._session.scalar(
            select(PointRow)
            .join(EquipmentRow, PointRow.equipment_id == EquipmentRow.id)
            .join(RoomRow, EquipmentRow.room_id == RoomRow.id)
            .join(SiteRow, RoomRow.site_id == SiteRow.id)
            .where(PointRow.id == point_id, SiteRow.organization_id == organization_id),
        )
        return None if row is None else _point(row)

    async def save_site(self, organization_id: UUID, site: Site) -> None:
        """Upsert by id."""
        await self._session.merge(
            SiteRow(
                id=site.id,
                organization_id=organization_id,
                name=site.name,
                address=site.address,
                timezone=site.timezone,
                control_time=site.control_time,
                control_window_minutes=int(site.control_window.total_seconds() // 60),
            ),
        )
        await self._session.flush()

    async def save_room(self, room: Room) -> None:
        """Upsert by id."""
        await self._session.merge(RoomRow(id=room.id, site_id=room.site_id, name=room.name))
        await self._session.flush()

    async def save_equipment(self, equipment: Equipment) -> None:
        """Upsert by id."""
        await self._session.merge(
            EquipmentRow(id=equipment.id, room_id=equipment.room_id, name=equipment.name, kind=equipment.kind.value),
        )
        await self._session.flush()

    async def save_point(self, point: MeasurementPoint) -> None:
        """Upsert by id."""
        settings = point.settings
        await self._session.merge(
            PointRow(
                id=point.id,
                equipment_id=point.equipment_id,
                name=point.name,
                low_threshold=settings.low_threshold,
                high_threshold=settings.high_threshold,
                deviation_seconds=int(settings.deviation_duration.total_seconds()),
                recovery_seconds=int(settings.recovery_duration.total_seconds()),
                expected_interval_seconds=int(settings.expected_interval.total_seconds()),
                offline_timeout_seconds=int(settings.offline_timeout.total_seconds()),
                profile=settings.profile.value,
            ),
        )
        await self._session.flush()

    async def has_children(self, kind: InventoryKind, entity_id: UUID) -> bool:
        """Dependent rows that deleting would orphan or rewrite."""
        match kind:
            case InventoryKind.SITE:
                checks = [exists().where(RoomRow.site_id == entity_id)]
            case InventoryKind.ROOM:
                checks = [exists().where(EquipmentRow.room_id == entity_id)]
            case InventoryKind.EQUIPMENT:
                checks = [exists().where(PointRow.equipment_id == entity_id)]
            case InventoryKind.POINT:
                checks = [
                    exists().where(AssignmentRow.point_id == entity_id),
                    exists().where(MeasurementRow.point_id == entity_id),
                ]
        for check in checks:
            if await self._session.scalar(select(check)):
                return True
        return False

    async def delete(self, kind: InventoryKind, entity_id: UUID) -> None:
        """Delete an empty entity."""
        table: type[SiteRow] | type[RoomRow] | type[EquipmentRow] | type[PointRow]
        match kind:
            case InventoryKind.SITE:
                table = SiteRow
            case InventoryKind.ROOM:
                table = RoomRow
            case InventoryKind.EQUIPMENT:
                table = EquipmentRow
            case InventoryKind.POINT:
                table = PointRow
        await self._session.execute(delete(table).where(table.id == entity_id))

    async def point_records(
        self,
        organization_id: UUID,
        *,
        site_id: UUID | None = None,
        equipment_id: UUID | None = None,
        point_ids: Sequence[UUID] | None = None,
    ) -> list[PointRecord]:
        """Points with location and settings."""
        query = location_query().where(SiteRow.organization_id == organization_id)
        if site_id is not None:
            query = query.where(SiteRow.id == site_id)
        if equipment_id is not None:
            query = query.where(EquipmentRow.id == equipment_id)
        if point_ids is not None:
            if not point_ids:
                return []
            query = query.where(PointRow.id.in_(point_ids))
        result = await self._session.execute(query)
        return [record_from(row) for row in result.all()]

    async def point_record(self, point_id: UUID) -> PointRecord | None:
        """Internal lookup without an organization filter."""
        result = await self._session.execute(location_query().where(PointRow.id == point_id))
        row = result.first()
        return None if row is None else record_from(row)
