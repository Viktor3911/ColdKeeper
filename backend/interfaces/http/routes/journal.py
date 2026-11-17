"""Daily journal and raw measurements: screen data and file exports."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response

from backend.application.journal import ExportFormat, JournalFilter
from backend.application.ports import ExportFile
from backend.interfaces.http.dependencies import ContainerDep, ReaderDep
from backend.interfaces.http.schemas import JournalOut, RawOut

router = APIRouter(prefix="/api/v1/journal", tags=["journal"])

RAW_SCREEN_LIMIT = 1000


def journal_filter(
    first: Annotated[date, Query(description="Первый день (местная дата объекта)")],
    last: Annotated[date, Query(description="Последний день включительно")],
    site_id: UUID | None = None,
    equipment_id: UUID | None = None,
) -> JournalFilter:
    """Query parameters shared by the journal endpoints."""
    return JournalFilter(first_day=first, last_day=last, site_id=site_id, equipment_id=equipment_id)


FilterDep = Annotated[JournalFilter, Depends(journal_filter)]


def _download(file: ExportFile, stem: str, query: JournalFilter) -> Response:
    suffix = "_demo" if file.has_simulation else ""
    name = f"{stem}_{query.first_day.isoformat()}_{query.last_day.isoformat()}{suffix}.{file.extension}"
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("/daily")
async def daily(container: ContainerDep, actor: ReaderDep, query: FilterDep) -> JournalOut:
    """Daily journal rows."""
    return JournalOut.of(await container.journal.daily(actor, query))


@router.get("/daily/export", response_class=Response)
async def daily_export(
    container: ContainerDep,
    actor: ReaderDep,
    query: FilterDep,
    file_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.CSV,
) -> Response:
    """Daily journal file (CSV for Russian Excel or XLSX)."""
    return _download(await container.journal.export_daily(actor, query, file_format), "journal", query)


@router.get("/form/export", response_class=Response)
async def form_export(container: ContainerDep, actor: ReaderDep, query: FilterDep) -> Response:
    """Word journal in the layout of the recommended sample (SanPiN 2.3/2.4.4282-26, appendix N 2)."""
    return _download(await container.journal.export_form(actor, query), "journal_sanpin", query)


@router.get("/raw")
async def raw(container: ContainerDep, actor: ReaderDep, query: FilterDep) -> RawOut:
    """Raw measurements (the newest on screen; everything in the export)."""
    return RawOut.of(await container.journal.raw(actor, query), RAW_SCREEN_LIMIT)


@router.get("/raw/export", response_class=Response)
async def raw_export(
    container: ContainerDep,
    actor: ReaderDep,
    query: FilterDep,
    file_format: Annotated[ExportFormat, Query(alias="format")] = ExportFormat.CSV,
) -> Response:
    """Raw measurements file."""
    return _download(await container.journal.export_raw(actor, query, file_format), "measurements", query)
