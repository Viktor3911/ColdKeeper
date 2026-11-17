"""The Word journal in the layout of SanPiN 2.3/2.4.4282-26, appendix N 2."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, date, datetime, time, timedelta

from docx import Document

from backend.adapters.export.docx_form import DocxJournalFormRenderer, format_cell
from backend.application.journal_form import FormCell, build_form
from backend.application.views import JournalTable
from backend.domain.equipment import PointLocation, Site
from backend.domain.journal import ControlState, ControlValue, DayStats, JournalRow
from backend.domain.sensors import MeasurementSource

SITE = Site(
    id=uuid.uuid4(),
    organization_id=uuid.uuid4(),
    name="Кафе",
    address="ул. Светланская, 1",
    timezone="Asia/Vladivostok",
    control_time=time(10, 0),
    control_window=timedelta(minutes=30),
)
EQUIPMENT = uuid.uuid4()


def _location(
    point_name: str, equipment_id: uuid.UUID = EQUIPMENT, equipment_name: str = "Холодильник"
) -> PointLocation:
    return PointLocation(
        organization_id=SITE.organization_id,
        organization_name="ООО Ромашка",
        site_id=SITE.id,
        site_name=SITE.name,
        timezone=SITE.timezone,
        room_id=uuid.uuid4(),
        room_name="Кухня",
        equipment_id=equipment_id,
        equipment_name=equipment_name,
        point_id=uuid.uuid5(uuid.NAMESPACE_DNS, point_name),
        point_name=point_name,
    )


def _row(location: PointLocation, day: date, control: ControlValue) -> JournalRow:
    stats = DayStats(sources=frozenset({MeasurementSource.DEVICE}))
    return JournalRow(location=location, day=day, control=control, stats=stats, coverage=1.0)


def _table() -> JournalTable:
    freezer = _location("Морозильная секция")
    fridge = _location("Холодильная секция")
    shelf = _location("Камера", uuid.uuid4(), "Шкаф №1")
    moment = datetime(2026, 10, 31, 0, 5, tzinfo=UTC)
    rows = [
        _row(freezer, date(2026, 10, 31), ControlValue(ControlState.OK, moment, -18.25)),
        _row(freezer, date(2026, 11, 1), ControlValue(ControlState.SENSOR_ERROR)),
        _row(fridge, date(2026, 10, 31), ControlValue(ControlState.OK, moment, 4.0)),
        _row(fridge, date(2026, 11, 1), ControlValue(ControlState.NO_DATA)),
        _row(shelf, date(2026, 10, 31), ControlValue(ControlState.OK, moment, 3.5)),
        _row(shelf, date(2026, 11, 1), ControlValue(ControlState.OK, moment, 3.6)),
    ]
    return JournalTable("ООО Ромашка", date(2026, 10, 31), date(2026, 11, 1), rows)


def test_one_page_per_month_with_a_row_per_unit() -> None:
    form = build_form(_table(), [SITE])
    assert [(page.year, page.month, page.days_in_month) for page in form.months] == [(2026, 10, 31), (2026, 11, 30)]
    october = form.months[0]
    assert [row.equipment_name for row in october.rows] == [
        "Холодильник (морозильная секция)",
        "Холодильник (холодильная секция)",
        "Шкаф №1",  # a single section is not repeated
    ]
    assert october.rows[0].cells == {31: FormCell(ControlState.OK, -18.25)}


def test_cell_texts_never_invent_values() -> None:
    assert format_cell(FormCell(ControlState.OK, -18.25)) == "-18,2"
    assert format_cell(FormCell(ControlState.NO_DATA, None)) == "—"
    assert format_cell(FormCell(ControlState.SENSOR_ERROR, None)) == "о.д."
    assert format_cell(None) == ""  # outside the requested period


def test_word_document_follows_the_sample_table() -> None:
    exported = DocxJournalFormRenderer().render(build_form(_table(), [SITE]))
    assert exported.extension == "docx"
    document = Document(io.BytesIO(exported.content))
    section = document.sections[0]
    assert section.page_width is not None and section.page_height is not None
    assert section.page_width > section.page_height  # landscape
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "учета температурного режима холодильного оборудования" in text
    assert "СанПиН 2.3/2.4.4282-26" in text
    assert "Месяц: октябрь 2026 г." in text and "Месяц: ноябрь 2026 г." in text
    october, november = document.tables
    assert len(october.columns) == 2 + 31
    assert len(november.columns) == 2 + 30
    assert october.cell(0, 0).text == "Наименование производственного помещения"
    assert october.cell(0, 1).text == "Наименование холодильного оборудования"
    assert october.cell(0, 2).text.startswith("Температура в градусах Цельсия")
    assert [october.cell(1, 1 + day).text for day in (1, 31)] == ["1", "31"]
    assert october.cell(2, 1 + 31).text == "-18,2"
    assert october.cell(2, 1 + 30).text == ""
    assert november.cell(2, 1 + 1).text == "о.д."
    assert november.cell(3, 1 + 1).text == "—"
    assert "ДЕМОНСТРАЦИОННЫЕ" not in text  # real devices only


def test_demo_data_is_marked_in_the_document() -> None:
    table = _table()
    rows = [
        JournalRow(row.location, row.day, row.control, DayStats(sources=frozenset({MeasurementSource.SIMULATOR})), 1.0)
        for row in table.rows
    ]
    demo = JournalTable(table.organization_name, table.first_day, table.last_day, rows)
    exported = DocxJournalFormRenderer().render(build_form(demo, [SITE]))
    document = Document(io.BytesIO(exported.content))
    assert exported.has_simulation
    assert any("ДЕМОНСТРАЦИОННЫЕ ДАННЫЕ" in paragraph.text for paragraph in document.paragraphs)
