"""Adapters without a database: UnitX payload, exports, passwords, token redaction."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from openpyxl import load_workbook
from pydantic import ValidationError

from backend.adapters.export.csv_export import CsvJournalExporter, format_cell, protect_text
from backend.adapters.export.xlsx_export import XlsxJournalExporter
from backend.adapters.security.passwords import ScryptParameters, ScryptPasswordHasher
from backend.adapters.unitx.payload import UnitXPayload, to_reading
from backend.application.views import JournalTable
from backend.domain.equipment import PointLocation
from backend.domain.errors import ValidationFailedError
from backend.domain.journal import ControlState, ControlValue, DayStats, JournalRow
from backend.domain.sensors import MeasurementSource
from backend.interfaces.logging_setup import redact

LOCATION = PointLocation(
    organization_id=uuid.uuid4(),
    organization_name="ООО Ромашка",
    site_id=uuid.uuid4(),
    site_name='=HYPERLINK("http://evil")',
    timezone="Asia/Vladivostok",
    room_id=uuid.uuid4(),
    room_name="Кухня",
    equipment_id=uuid.uuid4(),
    equipment_name="Морозильник",
    point_id=uuid.uuid4(),
    point_name="Камера",
)


def test_unitx_documented_body_is_accepted_with_extra_fields() -> None:
    payload = UnitXPayload.model_validate_json(
        '{"id":"utx-ae4634","ts":1792711142,"t":23.6,"rh":45.3,"ok":true,"rssi":-60,"fw":"1.2"}',
    )
    reading = to_reading(payload, rssi=-60)
    assert reading.hardware_id == "utx-ae4634"
    assert reading.measured_at == datetime.fromtimestamp(1792711142, tz=UTC)
    assert reading.temperature == 23.6
    assert reading.humidity == 45.3


def test_probe_failure_is_not_zero_degrees() -> None:
    payload = UnitXPayload.model_validate_json('{"id":"utx-1","ts":1792711142,"t":85.0,"ok":false}')
    reading = to_reading(payload)
    assert reading.sensor_ok is False
    assert reading.temperature is None


def test_empty_humidity_means_absent() -> None:
    payload = UnitXPayload.model_validate_json('{"id":"utx-1","ts":1792711142,"t":4.0,"rh":"","ok":true}')
    assert payload.rh is None


@pytest.mark.parametrize(
    "body",
    [
        '{"id":"utx-1","ts":1792711142,"t":"4","ok":true}',
        '{"id":"utx-1","ts":1792711142,"t":true,"ok":true}',
        '{"id":"utx-1","ts":1792711142123,"t":4.0,"ok":true}',
        '{"id":"utx-1","ts":"1792711142","t":4.0,"ok":true}',
        '{"id":"utx-1","ts":1792711142,"t":4.0,"ok":"yes"}',
        '{"id":"utx-1","ts":1792711142,"t":NaN,"ok":true}',
    ],
)
def test_invalid_payloads_are_rejected(body: str) -> None:
    with pytest.raises(ValidationError):
        UnitXPayload.model_validate_json(body)


def test_ok_true_requires_a_temperature() -> None:
    payload = UnitXPayload.model_validate_json('{"id":"utx-1","ts":1792711142,"ok":true}')
    with pytest.raises(ValidationFailedError):
        to_reading(payload)


def _table() -> JournalTable:
    rows = [
        JournalRow(
            location=LOCATION,
            day=date(2026, 11, 3),
            control=ControlValue(ControlState.OK, datetime(2026, 11, 3, 0, 4, tzinfo=UTC), -18.25),
            stats=DayStats(1400, 2, -19.5, -16.75, frozenset({MeasurementSource.SIMULATOR})),
            coverage=0.97,
        ),
        JournalRow(
            location=LOCATION,
            day=date(2026, 11, 4),
            control=ControlValue(ControlState.NO_DATA),
            stats=DayStats(),
            coverage=0.0,
        ),
    ]
    return JournalTable("ООО Ромашка", date(2026, 11, 3), date(2026, 11, 4), rows)


def test_csv_for_russian_excel() -> None:
    exported = CsvJournalExporter().daily(_table())
    assert exported.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    header, cells, second = csv.reader(io.StringIO(exported.content.decode("utf-8-sig")), delimiter=";")
    assert header[0] == "Организация"
    assert cells[1] == '\'=HYPERLINK("http://evil")'  # text that would be a formula is neutralized
    assert "03.11.2026" in cells
    assert "10:04" in cells  # local time of Vladivostok
    assert "-18,25" in cells  # negative number stays a number
    assert "симуляция" in cells
    assert "нет данных" in second
    assert exported.has_simulation


def test_formula_protection_is_for_text_only() -> None:
    assert protect_text("=1+1") == "'=1+1"
    assert protect_text("-сухой лёд") == "'-сухой лёд"
    assert protect_text("Кухня") == "Кухня"
    assert format_cell(-18.2) == "-18,2"


def test_xlsx_cells_are_typed_and_text_is_never_a_formula() -> None:
    exported = XlsxJournalExporter().daily(_table())
    sheet = load_workbook(io.BytesIO(exported.content)).active
    assert sheet is not None
    site = sheet.cell(row=2, column=2)
    assert site.data_type == "s"
    assert site.value == '=HYPERLINK("http://evil")'
    temperature = sheet.cell(row=2, column=8)
    assert temperature.value == -18.25
    day = sheet.cell(row=2, column=6).value
    assert isinstance(day, datetime)
    assert day.date() == date(2026, 11, 3)
    assert sheet.title.endswith("(симуляция)")


def test_scrypt_hashes_verify_and_detect_old_parameters() -> None:
    hasher = ScryptPasswordHasher(ScryptParameters(n=2**4, r=8, p=1))
    encoded = hasher.hash("correct horse battery")
    assert encoded.startswith("scrypt$16$8$1$")
    assert hasher.verify("correct horse battery", encoded)
    assert not hasher.verify("wrong password", encoded)
    assert not hasher.verify("anything", "garbage")
    assert not hasher.needs_rehash(encoded)
    assert ScryptPasswordHasher(ScryptParameters(n=2**5, r=8, p=1)).needs_rehash(encoded)


def test_default_scrypt_parameters_are_accepted_by_hashlib() -> None:
    hasher = ScryptPasswordHasher()
    assert hasher.verify("пароль-для-проверки", hasher.hash("пароль-для-проверки"))


def test_tokens_are_redacted_from_log_lines() -> None:
    line = 'POST /api/v1/ingest/unitx?token=AbC123-secret_value&rssi=-60 HTTP/1.1" 204'
    assert redact(line) == 'POST /api/v1/ingest/unitx?token=***&rssi=-60 HTTP/1.1" 204'


def test_ingest_time_window() -> None:
    payload = UnitXPayload.model_validate_json('{"id":"utx-1","ts":1792711142,"t":4.0,"ok":true}')
    reading = to_reading(payload)
    reading.check_time(reading.measured_at)
    with pytest.raises(ValidationFailedError):
        reading.check_time(reading.measured_at - timedelta(minutes=10))  # measurement 10 min in the future
    with pytest.raises(ValidationFailedError):
        reading.check_time(reading.measured_at + timedelta(days=31))
