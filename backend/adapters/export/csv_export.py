"""CSV for Russian Excel: ``;`` separator, UTF-8 with BOM, decimal comma, ``ДД.ММ.ГГГГ`` dates."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from datetime import date, datetime, time

from backend.adapters.export.columns import DAILY_HEADER, RAW_HEADER, Cell, Percent, daily_rows, raw_rows
from backend.application.ports import ExportFile
from backend.application.views import JournalTable, RawTable

# A text cell starting with one of these is a formula for spreadsheet programs.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def protect_text(value: str) -> str:
    """Neutralize formula injection in text cells; numeric cells are not passed here (negative °C stay numbers)."""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def format_cell(value: Cell) -> str:
    """Serialize a typed cell the way Russian Excel parses it."""
    match value:
        case None:
            return ""
        case Percent():
            return f"{value.value * 100:.0f}"
        case bool():
            return "да" if value else "нет"
        case int():
            return str(value)
        case float():
            return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        case datetime():
            return value.strftime("%d.%m.%Y %H:%M:%S")
        case date():
            return value.strftime("%d.%m.%Y")
        case time():
            return value.strftime("%H:%M") if value.second == 0 else value.strftime("%H:%M:%S")
        case str():
            return protect_text(value)


class CsvJournalExporter:
    """Same columns as XLSX (see :mod:`backend.adapters.export.columns`)."""

    def daily(self, table: JournalTable) -> ExportFile:
        """Daily journal."""
        return _file(DAILY_HEADER, daily_rows(table), table.has_simulation)

    def raw(self, table: RawTable) -> ExportFile:
        """Raw measurements."""
        return _file(RAW_HEADER, raw_rows(table), table.has_simulation)


def _file(header: tuple[str, ...], rows: Iterable[tuple[Cell, ...]], has_simulation: bool) -> ExportFile:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    for row in rows:
        writer.writerow(format_cell(cell) for cell in row)
    return ExportFile(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        extension="csv",
        has_simulation=has_simulation,
    )
