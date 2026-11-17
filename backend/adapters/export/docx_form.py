"""Word (DOCX) journal laid out like the recommended sample of SanPiN 2.3/2.4.4282-26, appendix N 2.

The sample fixes only the table: "Наименование производственного помещения", "Наименование холодильного
оборудования" and "Температура в градусах Цельсия, месяц/дни: (ежедневно)" with a column per day. Fonts, margins and
the header block are not regulated; they are chosen to print one month of a site on landscape A4.
"""

from __future__ import annotations

import io

from docx import Document
from docx.document import Document as DocxDocument
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.oxml.table import CT_Row
from docx.shared import Cm, Pt, RGBColor
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph

from backend.application.journal_form import SANPIN_REFERENCE, FormCell, FormMonth, TemperatureForm
from backend.application.ports import ExportFile
from backend.domain.journal import ControlState

_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_FONT = "Times New Roman"
_MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
# Landscape A4 (29.7 cm) minus 1.2 cm margins on both sides.
_ROOM_WIDTH = Cm(3.0)
_UNIT_WIDTH = Cm(4.2)
_DAYS_WIDTH = Cm(27.3 - 3.0 - 4.2)
_NO_DATA = "—"
_SENSOR_ERROR = "о.д."


def format_cell(cell: FormCell | None) -> str:
    """``-18,2`` with a decimal comma; a dash for no data; blank for days outside the period."""
    if cell is None:
        return ""
    if cell.state is ControlState.OK and cell.temperature is not None:
        return f"{cell.temperature:.1f}".replace(".", ",")
    return _SENSOR_ERROR if cell.state is ControlState.SENSOR_ERROR else _NO_DATA


class DocxJournalFormRenderer:
    """One page per site and month; the header row repeats if a page holds many units."""

    def render(self, form: TemperatureForm) -> ExportFile:
        """Build the document."""
        document = Document()
        _setup(document)
        if not form.months:
            _paragraph(document.add_paragraph(), "Нет точек измерения для выбранного фильтра.", size=12)
        for index, month in enumerate(form.months):
            if index:
                document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            _month_page(document, month, demo=form.has_simulation)
        document.core_properties.title = "Журнал учета температурного режима холодильного оборудования"
        document.core_properties.author = "ColdKeeper"
        buffer = io.BytesIO()
        document.save(buffer)
        return ExportFile(
            content=buffer.getvalue(),
            media_type=_MEDIA_TYPE,
            extension="docx",
            has_simulation=form.has_simulation,
        )


def _setup(document: DocxDocument) -> None:
    section = document.sections[0]
    section.orientation = WD_ORIENT.LANDSCAPE
    section.page_width, section.page_height = Cm(29.7), Cm(21.0)
    for side in ("left_margin", "right_margin"):
        setattr(section, side, Cm(1.2))
    section.top_margin = section.bottom_margin = Cm(1.2)
    style = document.styles["Normal"]
    style.font.name = _FONT
    style.font.size = Pt(11)
    # Cyrillic text uses the "hAnsi"/"cs"/"eastAsia" font slots in Word, not only "ascii".
    fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
    for slot in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(slot), _FONT)
    style.paragraph_format.space_after = Pt(0)


def _paragraph(
    paragraph: Paragraph,
    text: str,
    *,
    size: float = 11,
    bold: bool = False,
    align: WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH.LEFT,
    color: RGBColor | None = None,
) -> Paragraph:
    paragraph.alignment = align
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    return paragraph


def _month_page(document: DocxDocument, month: FormMonth, *, demo: bool) -> None:
    add = document.add_paragraph
    _paragraph(add(), f"Форма — {SANPIN_REFERENCE}", size=9, align=WD_ALIGN_PARAGRAPH.RIGHT)
    _paragraph(add(), "Журнал", size=14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _paragraph(
        add(),
        "учета температурного режима холодильного оборудования",
        size=14,
        bold=True,
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )
    add()
    _paragraph(add(), f"Организация: {month.organization_name}")
    site = month.site_name + (f", {month.site_address}" if month.site_address else "")
    _paragraph(add(), f"Объект: {site}")
    _paragraph(add(), f"Месяц: {_MONTHS[month.month - 1]} {month.year} г.", bold=True)
    if demo:
        _paragraph(
            add(),
            "ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ: значения получены от симулятора, а не от реальных датчиков.",
            bold=True,
            color=RGBColor(0xB4, 0x23, 0x18),
        )
    add()
    _table(document, month)
    add()
    control = month.control_time.strftime("%H:%M")
    notes = (
        f"Значения внесены автоматически по показаниям датчиков ColdKeeper: первое корректное измерение не ранее "
        f"{control} в течение {month.control_window_minutes} мин (местное время, {month.timezone}). "
        f"«{_NO_DATA}» — измерения за контрольное время нет; «{_SENSOR_ERROR}» — ошибка датчика, значение не получено; "
        "пустая ячейка — день вне выбранного периода. Пропуски не заполняются."
    )
    _paragraph(add(), notes, size=9)
    add()
    _paragraph(
        add(),
        "Ответственное лицо: __________________ (должность)   __________________ (Ф. И. О.)   __________ (подпись)",
    )


def _table(document: DocxDocument, month: FormMonth) -> None:
    days = month.days_in_month
    table = document.add_table(rows=2 + len(month.rows), cols=2 + days)
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    _compact_margins(table)
    day_width = int(_DAYS_WIDTH / days)

    header, numbers = table.rows[0], table.rows[1]
    for row in (header, numbers):
        # python-docx has no public API for repeated header rows.
        _repeat_as_header(row._tr)
    room = header.cells[0].merge(numbers.cells[0])
    unit = header.cells[1].merge(numbers.cells[1])
    temperature = header.cells[2].merge(header.cells[1 + days])
    _cell(room, "Наименование производственного помещения", size=9, bold=True)
    _cell(unit, "Наименование холодильного оборудования", size=9, bold=True)
    _cell(temperature, "Температура в градусах Цельсия\nмесяц/дни: (ежедневно)", size=9, bold=True)
    for day in range(1, days + 1):
        _cell(numbers.cells[1 + day], str(day), size=8, bold=True)

    for index, unit_row in enumerate(month.rows):
        cells = table.rows[2 + index].cells
        _cell(cells[0], unit_row.room_name, size=9, align=WD_ALIGN_PARAGRAPH.LEFT)
        _cell(cells[1], unit_row.equipment_name, size=9, align=WD_ALIGN_PARAGRAPH.LEFT)
        for day in range(1, days + 1):
            _cell(cells[1 + day], format_cell(unit_row.cells.get(day)), size=7)

    for row in table.rows:
        row.cells[0].width = _ROOM_WIDTH
        row.cells[1].width = _UNIT_WIDTH
        for day in range(1, days + 1):
            row.cells[1 + day].width = day_width


def _cell(
    cell: _Cell,
    text: str,
    *,
    size: float,
    bold: bool = False,
    align: WD_ALIGN_PARAGRAPH = WD_ALIGN_PARAGRAPH.CENTER,
) -> None:
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
    paragraph = cell.paragraphs[0]
    paragraph.text = ""
    _paragraph(paragraph, text, size=size, bold=bold, align=align)


def _repeat_as_header(row_element: CT_Row) -> None:
    properties = row_element.get_or_add_trPr()
    marker = OxmlElement("w:tblHeader")
    marker.set(qn("w:val"), "true")
    properties.append(marker)


def _compact_margins(table: Table) -> None:
    """Narrow cell padding so 31 day columns fit the page."""
    properties = table._tbl.tblPr  # cell margins are not exposed by python-docx
    margins = OxmlElement("w:tblCellMar")
    for side, twips in (("top", 20), ("bottom", 20), ("left", 30), ("right", 30)):
        element = OxmlElement(f"w:{side}")
        element.set(qn("w:w"), str(twips))
        element.set(qn("w:type"), "dxa")
        margins.append(element)
    properties.append(margins)
