"""The printable journal in the layout of the recommended sample of SanPiN 2.3/2.4.4282-26, appendix N 2.

The sample is a monthly table: one row per room and refrigeration unit, one column per day, the temperature in °C.
Values come from the daily journal rule (the control measurement of the day); nothing is filled in for missing days.
"""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from uuid import UUID

from backend.application.views import JournalTable
from backend.domain.equipment import Site
from backend.domain.journal import ControlState, JournalRow

SANPIN_REFERENCE = "по приложению N 2 к СанПиН 2.3/2.4.4282-26 (рекомендуемый образец)"


@dataclass(frozen=True, slots=True)
class FormCell:
    """A day of a unit: the control temperature or why there is none."""

    state: ControlState
    temperature: float | None


@dataclass(frozen=True, slots=True)
class FormRow:
    """A refrigeration unit (or a section of it) in a room."""

    room_name: str
    equipment_name: str
    cells: dict[int, FormCell]  # day of month → value; days outside the period are absent


@dataclass(frozen=True, slots=True)
class FormMonth:
    """One page of the journal: one site, one calendar month."""

    organization_name: str
    site_name: str
    site_address: str
    timezone: str
    control_time: time
    control_window_minutes: int
    year: int
    month: int
    rows: list[FormRow]

    @property
    def days_in_month(self) -> int:
        """28–31 day columns."""
        return calendar.monthrange(self.year, self.month)[1]


@dataclass(frozen=True, slots=True)
class TemperatureForm:
    """All pages of the requested period."""

    months: list[FormMonth]
    has_simulation: bool


def _unit_name(row: JournalRow, sections_per_equipment: dict[UUID, int]) -> str:
    """Equipment name; a unit with several measured sections lists the section (e.g. the freezer part)."""
    location = row.location
    if sections_per_equipment.get(location.equipment_id, 0) > 1:
        return f"{location.equipment_name} ({location.point_name.lower()})"
    return location.equipment_name


def build_form(table: JournalTable, sites: Sequence[Site]) -> TemperatureForm:
    """Group daily journal rows into site × month pages with unit rows and day cells."""
    by_site = {site.id: site for site in sites}
    sections: dict[UUID, set[UUID]] = {}
    for row in table.rows:
        sections.setdefault(row.location.equipment_id, set()).add(row.location.point_id)
    sections_per_equipment = {equipment: len(points) for equipment, points in sections.items()}

    pages: dict[tuple[UUID, int, int], dict[UUID, FormRow]] = {}
    for row in table.rows:
        key = (row.location.site_id, row.day.year, row.day.month)
        units = pages.setdefault(key, {})
        unit = units.get(row.location.point_id)
        if unit is None:
            unit = FormRow(row.location.room_name, _unit_name(row, sections_per_equipment), {})
            units[row.location.point_id] = unit
        unit.cells[row.day.day] = FormCell(row.control.state, row.control.temperature)

    months: list[FormMonth] = []
    for (site_id, year, month), units in sorted(pages.items(), key=lambda item: (item[0][1], item[0][2])):
        site = by_site.get(site_id)
        if site is None:
            continue
        months.append(
            FormMonth(
                organization_name=table.organization_name,
                site_name=site.name,
                site_address=site.address,
                timezone=site.timezone,
                control_time=site.control_time,
                control_window_minutes=int(site.control_window.total_seconds() // 60),
                year=year,
                month=month,
                rows=list(units.values()),
            ),
        )
    return TemperatureForm(months=months, has_simulation=table.has_simulation)
