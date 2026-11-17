"""Measurements: idempotent insert, chart series and journal aggregates over explicit UTC day ranges.

Local days are computed by the domain (Python ``zoneinfo``) and passed in as ranges, so the database never
applies its own time zone rules to journal days.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Date, DateTime, and_, column, func, select, values
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.expression import Values

from backend.adapters.db.inventory import location_query, record_from
from backend.adapters.db.models import MeasurementRow, PointRow, SensorRow
from backend.application.views import RawRow, SeriesPoint
from backend.domain.journal import DayRange, DayStats, WindowReading
from backend.domain.sensors import MeasurementSource
from backend.domain.telemetry import Measurement


def _measurement(row: MeasurementRow) -> Measurement:
    return Measurement(
        sensor_id=row.sensor_id,
        assignment_id=row.assignment_id,
        point_id=row.point_id,
        measured_at=row.measured_at,
        received_at=row.received_at,
        temperature=row.temperature,
        sensor_ok=row.sensor_ok,
        source=MeasurementSource(row.source),
        humidity=row.humidity,
        rssi=row.rssi,
    )


def _ranges(ranges: Sequence[DayRange], name: str) -> Values:
    return values(
        column("day", Date),
        column("range_start", DateTime(timezone=True)),
        column("range_end", DateTime(timezone=True)),
        name=name,
    ).data([(item.day, item.start, item.end) for item in ranges])


_VALID = and_(MeasurementRow.sensor_ok.is_(True), MeasurementRow.temperature.is_not(None))


class SqlMeasurementRepository:
    """:class:`backend.application.ports.MeasurementRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, sensor_id: UUID, measured_at: datetime) -> Measurement | None:
        """By the unique key."""
        row = await self._session.scalar(
            select(MeasurementRow).where(
                MeasurementRow.sensor_id == sensor_id, MeasurementRow.measured_at == measured_at
            ),
        )
        return None if row is None else _measurement(row)

    async def add(self, measurement: Measurement) -> bool:
        """``INSERT … ON CONFLICT DO NOTHING``: a concurrent duplicate never raises."""
        statement = (
            insert(MeasurementRow)
            .values(
                sensor_id=measurement.sensor_id,
                assignment_id=measurement.assignment_id,
                point_id=measurement.point_id,
                measured_at=measurement.measured_at,
                received_at=measurement.received_at,
                temperature=measurement.temperature,
                sensor_ok=measurement.sensor_ok,
                source=measurement.source.value,
                humidity=measurement.humidity,
                rssi=measurement.rssi,
            )
            .on_conflict_do_nothing(constraint="uq_measurements_sensor_time")
            .returning(MeasurementRow.id)
        )
        return (await self._session.scalar(statement)) is not None

    async def latest_for_sensor(self, sensor_id: UUID) -> Measurement | None:
        """Newest of a sensor."""
        row = await self._session.scalar(
            select(MeasurementRow)
            .where(MeasurementRow.sensor_id == sensor_id)
            .order_by(MeasurementRow.measured_at.desc())
            .limit(1),
        )
        return None if row is None else _measurement(row)

    async def latest_for_point(self, point_id: UUID) -> Measurement | None:
        """Newest of a point."""
        row = await self._session.scalar(
            select(MeasurementRow)
            .where(MeasurementRow.point_id == point_id)
            .order_by(MeasurementRow.measured_at.desc())
            .limit(1),
        )
        return None if row is None else _measurement(row)

    async def series(self, point_id: UUID, start: datetime, end: datetime) -> list[SeriesPoint]:
        """Chart data."""
        result = await self._session.execute(
            select(
                MeasurementRow.measured_at, MeasurementRow.temperature, MeasurementRow.sensor_ok, MeasurementRow.source
            )
            .where(
                MeasurementRow.point_id == point_id,
                MeasurementRow.measured_at >= start,
                MeasurementRow.measured_at < end,
            )
            .order_by(MeasurementRow.measured_at),
        )
        return [
            SeriesPoint(measured_at=moment, temperature=temperature, sensor_ok=ok, source=MeasurementSource(source))
            for moment, temperature, ok, source in result.tuples()
        ]

    async def raw(self, point_ids: Sequence[UUID], start: datetime, end: datetime) -> list[RawRow]:
        """Raw rows with locations."""
        if not point_ids:
            return []
        query = (
            location_query()
            .add_columns(MeasurementRow, SensorRow.hardware_id)
            .join(MeasurementRow, MeasurementRow.point_id == PointRow.id)
            .join(SensorRow, MeasurementRow.sensor_id == SensorRow.id)
            .where(PointRow.id.in_(point_ids), MeasurementRow.measured_at >= start, MeasurementRow.measured_at < end)
            .order_by(MeasurementRow.measured_at)
        )
        result = await self._session.execute(query)
        rows: list[RawRow] = []
        for row in result.all():
            record = record_from(row[:5])
            measurement: MeasurementRow = row[5]
            rows.append(
                RawRow(
                    location=record.location,
                    sensor_hardware_id=row[6],
                    measured_at=measurement.measured_at,
                    received_at=measurement.received_at,
                    temperature=measurement.temperature,
                    sensor_ok=measurement.sensor_ok,
                    source=MeasurementSource(measurement.source),
                    humidity=measurement.humidity,
                ),
            )
        return rows

    async def day_stats(self, point_ids: Sequence[UUID], days: Sequence[DayRange]) -> dict[tuple[UUID, date], DayStats]:
        """Count, min and max of valid readings, failed readings and sources per point and day."""
        if not point_ids or not days:
            return {}
        ranges = _ranges(days, "journal_days")
        temperature = MeasurementRow.temperature
        query = (
            select(
                MeasurementRow.point_id,
                ranges.c.day,
                func.count().filter(_VALID),
                func.count().filter(MeasurementRow.sensor_ok.is_(False)),
                func.min(temperature).filter(_VALID),
                func.max(temperature).filter(_VALID),
                func.array_agg(func.distinct(MeasurementRow.source)),
            )
            .select_from(MeasurementRow)
            .join(
                ranges,
                and_(
                    MeasurementRow.measured_at >= ranges.c.range_start,
                    MeasurementRow.measured_at < ranges.c.range_end,
                ),
            )
            .where(MeasurementRow.point_id.in_(point_ids))
            .group_by(MeasurementRow.point_id, ranges.c.day)
        )
        result = await self._session.execute(query)
        stats: dict[tuple[UUID, date], DayStats] = {}
        for point_id, day, valid, errors, minimum, maximum, sources in result.tuples():
            stats[(point_id, day)] = DayStats(
                valid_count=valid,
                error_count=errors,
                minimum=None if minimum is None else float(minimum),
                maximum=None if maximum is None else float(maximum),
                sources=frozenset(MeasurementSource(source) for source in sources),
            )
        return stats

    async def in_windows(
        self,
        point_ids: Sequence[UUID],
        windows: Sequence[DayRange],
    ) -> dict[tuple[UUID, date], list[WindowReading]]:
        """Measurements inside each day's control window."""
        if not point_ids or not windows:
            return {}
        ranges = _ranges(windows, "control_windows")
        query = (
            select(
                MeasurementRow.point_id,
                ranges.c.day,
                MeasurementRow.measured_at,
                MeasurementRow.temperature,
                MeasurementRow.sensor_ok,
                MeasurementRow.source,
            )
            .select_from(MeasurementRow)
            .join(
                ranges,
                and_(
                    MeasurementRow.measured_at >= ranges.c.range_start,
                    MeasurementRow.measured_at < ranges.c.range_end,
                ),
            )
            .where(MeasurementRow.point_id.in_(point_ids))
            .order_by(MeasurementRow.measured_at)
        )
        result = await self._session.execute(query)
        readings: dict[tuple[UUID, date], list[WindowReading]] = defaultdict(list)
        for point_id, day, moment, temperature, ok, source in result.tuples():
            readings[(point_id, day)].append(
                WindowReading(
                    measured_at=moment, temperature=temperature, sensor_ok=ok, source=MeasurementSource(source)
                ),
            )
        return dict(readings)
