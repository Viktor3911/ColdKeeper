"""Daily journal and raw measurements of a period, on screen and as files."""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from backend.application.journal_form import build_form
from backend.application.ports import (
    ExportFile,
    JournalExporter,
    JournalFormRenderer,
    UnitOfWork,
    UnitOfWorkFactory,
)
from backend.application.views import JournalTable, PointRecord, RawTable
from backend.domain.equipment import Site
from backend.domain.errors import NotFoundError, ValidationFailedError
from backend.domain.journal import DayStats, JournalRow, build_row, check_period, control_windows, local_days
from backend.domain.organizations import Actor

MAX_RAW_DAYS = 31


class ExportFormat(enum.StrEnum):
    """Supported file formats."""

    CSV = "csv"
    XLSX = "xlsx"


@dataclass(frozen=True, slots=True)
class JournalFilter:
    """Which part of the organization and which local dates (inclusive)."""

    first_day: date
    last_day: date
    site_id: UUID | None = None
    equipment_id: UUID | None = None


class JournalService:
    """Journal rows are built from stored measurements only: no interpolation, zeros or repeated values."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        exporters: dict[ExportFormat, JournalExporter],
        form_renderer: JournalFormRenderer,
    ) -> None:
        self._uow_factory = uow_factory
        self._exporters = exporters
        self._form_renderer = form_renderer

    async def daily(self, actor: Actor, query: JournalFilter) -> JournalTable:
        """One row per point and local day; days without data are present."""
        check_period(query.first_day, query.last_day)
        async with self._uow_factory() as uow:
            organization = await uow.organizations.get(actor.organization_id)
            records = await self._records(actor, query, uow)
            sites = {site.id: site for site in await uow.inventory.sites(actor.organization_id)}
            rows: list[JournalRow] = []
            for site_id in dict.fromkeys(record.location.site_id for record in records):
                site_records = [record for record in records if record.location.site_id == site_id]
                rows.extend(await _site_rows(uow, sites[site_id], site_records, query))
        return JournalTable(
            organization_name=organization.name if organization else "",
            first_day=query.first_day,
            last_day=query.last_day,
            rows=rows,
        )

    async def raw(self, actor: Actor, query: JournalFilter) -> RawTable:
        """Every stored measurement of the period (local days of each site)."""
        check_period(query.first_day, query.last_day)
        if (query.last_day - query.first_day).days + 1 > MAX_RAW_DAYS:
            raise ValidationFailedError(f"Исходные измерения — не больше {MAX_RAW_DAYS} дней за раз")
        async with self._uow_factory() as uow:
            organization = await uow.organizations.get(actor.organization_id)
            records = await self._records(actor, query, uow)
            rows = []
            for site in await uow.inventory.sites(actor.organization_id):
                point_ids = [record.location.point_id for record in records if record.location.site_id == site.id]
                if not point_ids:
                    continue
                days = local_days(query.first_day, query.last_day, site.zone)
                rows.extend(await uow.measurements.raw(point_ids, days[0].start, days[-1].end))
        return RawTable(
            organization_name=organization.name if organization else "",
            first_day=query.first_day,
            last_day=query.last_day,
            rows=rows,
        )

    async def export_daily(self, actor: Actor, query: JournalFilter, file_format: ExportFormat) -> ExportFile:
        """The daily journal as a file; rendering runs in a thread (XLSX is CPU-bound)."""
        table = await self.daily(actor, query)
        return await asyncio.to_thread(self._exporters[file_format].daily, table)

    async def export_raw(self, actor: Actor, query: JournalFilter, file_format: ExportFormat) -> ExportFile:
        """Raw measurements as a file."""
        table = await self.raw(actor, query)
        return await asyncio.to_thread(self._exporters[file_format].raw, table)

    async def export_form(self, actor: Actor, query: JournalFilter) -> ExportFile:
        """The journal by the SanPiN sample: one page per site and month, control values from the daily rule."""
        table = await self.daily(actor, query)
        async with self._uow_factory() as uow:
            sites = await uow.inventory.sites(actor.organization_id)
        return await asyncio.to_thread(self._form_renderer.render, build_form(table, sites))

    @staticmethod
    async def _records(actor: Actor, query: JournalFilter, uow: UnitOfWork) -> list[PointRecord]:
        org = actor.organization_id
        if query.site_id is not None and await uow.inventory.get_site(org, query.site_id) is None:
            raise NotFoundError("Объект не найден")
        if query.equipment_id is not None and await uow.inventory.get_equipment(org, query.equipment_id) is None:
            raise NotFoundError("Оборудование не найдено")
        return await uow.inventory.point_records(org, site_id=query.site_id, equipment_id=query.equipment_id)


async def _site_rows(uow: UnitOfWork, site: Site, records: list[PointRecord], query: JournalFilter) -> list[JournalRow]:
    """Rows of one site: its time zone defines the days and the control window."""
    zone = site.zone
    days = local_days(query.first_day, query.last_day, zone)
    windows = control_windows(days, zone, site.control_time, site.control_window)
    point_ids = [record.location.point_id for record in records]
    stats = await uow.measurements.day_stats(point_ids, days)
    readings = await uow.measurements.in_windows(point_ids, windows)
    return [
        build_row(
            record.location,
            day,
            readings.get((record.location.point_id, day.day), []),
            stats.get((record.location.point_id, day.day), DayStats()),
            record.settings.expected_interval,
        )
        for record in records
        for day in days
    ]
