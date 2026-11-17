"""Shared table layout of the exports; CSV and XLSX differ only in how cells are serialized."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from backend.application.views import JournalTable, RawTable
from backend.domain.journal import ControlState, JournalRow
from backend.domain.sensors import MeasurementSource


@dataclass(frozen=True, slots=True)
class Percent:
    """A 0…1 share shown as a percentage."""

    value: float


Cell = str | float | int | date | time | datetime | Percent | None

SOURCE_LABELS = {MeasurementSource.DEVICE: "датчик", MeasurementSource.SIMULATOR: "симуляция"}
CONTROL_LABELS = {
    ControlState.OK: "есть измерение",
    ControlState.NO_DATA: "нет данных",
    ControlState.SENSOR_ERROR: "ошибка датчика",
}

DAILY_HEADER = (
    "Организация",
    "Объект",
    "Помещение",
    "Оборудование",
    "Точка",
    "Дата",
    "Время измерения",
    "Температура, °C",
    "Контрольное измерение",
    "Мин. за сутки, °C",
    "Макс. за сутки, °C",
    "Показаний за сутки",
    "Покрытие суток, %",
    "Источник",
)

RAW_HEADER = (
    "Организация",
    "Объект",
    "Помещение",
    "Оборудование",
    "Точка",
    "Датчик",
    "Дата",
    "Время (местное)",
    "Время измерения, UTC",
    "Температура, °C",
    "Состояние датчика",
    "Влажность, %",
    "Источник",
    "Получено, UTC",
)


def sources_label(sources: frozenset[MeasurementSource]) -> str:
    """``датчик``, ``симуляция`` or both on the day of a switch."""
    if not sources:
        return "—"
    return ", ".join(SOURCE_LABELS[source] for source in sorted(sources))


def daily_rows(table: JournalTable) -> Iterator[tuple[Cell, ...]]:
    """Cells of the daily journal, one row per point and day."""
    for row in table.rows:
        yield _daily_row(table.organization_name, row)


def _daily_row(organization: str, row: JournalRow) -> tuple[Cell, ...]:
    location = row.location
    local_time = None if row.control.measured_at is None else row.control.measured_at.astimezone(location.zone)
    return (
        organization,
        location.site_name,
        location.room_name,
        location.equipment_name,
        location.point_name,
        row.day,
        None if local_time is None else local_time.time().replace(second=0, microsecond=0),
        row.control.temperature,
        CONTROL_LABELS[row.control.state],
        row.stats.minimum,
        row.stats.maximum,
        row.stats.valid_count,
        Percent(row.coverage),
        sources_label(row.sources),
    )


def raw_rows(table: RawTable) -> Iterator[tuple[Cell, ...]]:
    """Cells of the raw measurements."""
    for row in table.rows:
        location = row.location
        local = row.measured_at.astimezone(location.zone)
        yield (
            table.organization_name,
            location.site_name,
            location.room_name,
            location.equipment_name,
            location.point_name,
            row.sensor_hardware_id,
            local.date(),
            local.time().replace(microsecond=0),
            _utc(row.measured_at),
            row.temperature,
            "норма" if row.sensor_ok else "ошибка датчика",
            row.humidity,
            SOURCE_LABELS[row.source],
            _utc(row.received_at),
        )


def _utc(moment: datetime) -> datetime:
    """Naive UTC value for spreadsheet cells (the column header names the zone)."""
    return moment.astimezone(UTC).replace(tzinfo=None, microsecond=0)
