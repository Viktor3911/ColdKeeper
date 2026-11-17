"""XLSX with typed cells (numbers, dates) through openpyxl's write-only mode."""

from __future__ import annotations

import io
from collections.abc import Iterable
from datetime import date, datetime, time

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell as SheetCell
from openpyxl.styles import Font
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

from backend.adapters.export.columns import DAILY_HEADER, RAW_HEADER, Cell, Percent, daily_rows, raw_rows
from backend.application.ports import ExportFile
from backend.application.views import JournalTable, RawTable

_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FORMATS: dict[type, str] = {
    datetime: "DD.MM.YYYY HH:MM:SS",
    date: "DD.MM.YYYY",
    time: "HH:MM",
    float: "0.0#",
}


class XlsxJournalExporter:
    """Same columns as CSV; text cells are explicitly strings, so a leading ``=`` is never a formula."""

    def daily(self, table: JournalTable) -> ExportFile:
        """Daily journal."""
        title = "Журнал (симуляция)" if table.has_simulation else "Журнал"
        return _file(title, DAILY_HEADER, daily_rows(table), table.has_simulation)

    def raw(self, table: RawTable) -> ExportFile:
        """Raw measurements."""
        title = "Измерения (симуляция)" if table.has_simulation else "Измерения"
        return _file(title, RAW_HEADER, raw_rows(table), table.has_simulation)


def _file(title: str, header: tuple[str, ...], rows: Iterable[tuple[Cell, ...]], has_simulation: bool) -> ExportFile:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title=title[:31])
    sheet.column_dimensions["A"].width = 22
    bold = Font(bold=True)
    header_cells = []
    for name in header:
        cell = WriteOnlyCell(sheet, value=name)
        cell.font = bold
        header_cells.append(cell)
    sheet.append(header_cells)
    for row in rows:
        sheet.append([_cell(sheet, value) for value in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return ExportFile(
        content=buffer.getvalue(), media_type=_MEDIA_TYPE, extension="xlsx", has_simulation=has_simulation
    )


def _cell(sheet: WriteOnlyWorksheet, value: Cell) -> SheetCell:
    if isinstance(value, Percent):
        cell = WriteOnlyCell(sheet, value=value.value)
        cell.number_format = "0%"
        return cell
    cell = WriteOnlyCell(sheet)
    cell.value = value
    if isinstance(value, str):
        # openpyxl treats a string starting with "=" as a formula unless the type is forced.
        cell.data_type = "s"
    for kind, number_format in _FORMATS.items():
        if type(value) is kind:
            cell.number_format = number_format
    return cell
