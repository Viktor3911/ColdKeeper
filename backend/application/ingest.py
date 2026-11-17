"""The single use case that accepts readings from any source (UnitX devices and the simulator alike)."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from backend.application.incidents import IncidentRecorder
from backend.application.ports import Clock, SecretIssuer, UnitOfWork, UnitOfWorkFactory
from backend.domain.errors import AuthenticationError, ConflictError, PermissionDeniedError
from backend.domain.monitoring import apply_reading, is_live
from backend.domain.sensors import Sensor
from backend.domain.telemetry import Measurement, Reading, round_temperature


class IngestOutcome(enum.StrEnum):
    """What happened to an accepted reading (all are successful responses)."""

    STORED = "stored"  # fresh: stored and evaluated
    STORED_LATE = "stored_late"  # stored as history, the live status is unchanged
    STORED_UNASSIGNED = "stored_unassigned"  # the sensor had no point at that moment
    DUPLICATE = "duplicate"  # identical repeat of a stored reading


class IngestReading:
    """Authenticate the device, store the reading idempotently and update monitoring — in one transaction.

    The source label comes from the sensor registration, so the simulator and a real UnitX go through the
    same code; there is no demo branch.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretIssuer,
        incidents: IncidentRecorder,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets
        self._incidents = incidents

    async def __call__(self, token: str, reading: Reading) -> IngestOutcome:
        """Process one reading; raises on authentication, validation or conflicting data."""
        now = self._clock.now()
        reading.check_time(now)
        async with self._uow_factory() as uow:
            sensor = await self._authenticate(uow, token, reading)
            existing = await uow.measurements.get(sensor.id, reading.measured_at)
            if existing is not None:
                return _repeat(existing, reading)

            assignment = await uow.assignments.at(sensor.id, reading.measured_at)
            record = None if assignment is None else await uow.inventory.point_record(assignment.point_id)
            if assignment is None or record is None:
                if not await uow.measurements.add(_measurement(sensor, reading, now, None, None)):
                    return await _resolve_race(uow, sensor, reading)
                await uow.commit()
                return IngestOutcome.STORED_UNASSIGNED

            measurement = _measurement(sensor, reading, now, assignment.id, assignment.point_id)
            if now - reading.measured_at > record.settings.late_threshold:
                # Too old to affect the live status whatever the state is: no lock needed (history loads fast).
                if not await uow.measurements.add(measurement):
                    return await _resolve_race(uow, sensor, reading)
                await uow.commit()
                return IngestOutcome.STORED_LATE

            # Lock the point state first: concurrent readings of one point are applied one at a time.
            state = await uow.point_states.lock(record.location.point_id)
            if not await uow.measurements.add(measurement):
                return await _resolve_race(uow, sensor, reading)
            outcome = IngestOutcome.STORED_LATE
            if is_live(state, record.settings, reading.measured_at, now):
                evaluation = apply_reading(
                    state,
                    record.settings,
                    measured_at=measurement.measured_at,
                    received_at=now,
                    temperature=measurement.temperature,
                    sensor_ok=measurement.sensor_ok,
                )
                await uow.point_states.save(evaluation.state)
                await self._incidents.record(uow, record.location, evaluation.transitions, now)
                outcome = IngestOutcome.STORED
            await uow.commit()
            return outcome

    async def _authenticate(self, uow: UnitOfWork, token: str, reading: Reading) -> Sensor:
        sensor = await uow.sensors.get_by_token_hash(self._secrets.digest(token))
        if sensor is None:
            raise AuthenticationError("Неверный или отозванный ключ устройства")
        if sensor.hardware_id != reading.hardware_id:
            raise PermissionDeniedError("Аппаратный ID не соответствует ключу устройства")
        return sensor


def _measurement(
    sensor: Sensor,
    reading: Reading,
    now: datetime,
    assignment_id: UUID | None,
    point_id: UUID | None,
) -> Measurement:
    return Measurement(
        sensor_id=sensor.id,
        assignment_id=assignment_id,
        point_id=point_id,
        measured_at=reading.measured_at,
        received_at=now,
        temperature=round_temperature(reading.temperature),
        sensor_ok=reading.sensor_ok,
        source=sensor.source,
        humidity=reading.humidity,
        rssi=reading.rssi,
    )


async def _resolve_race(uow: UnitOfWork, sensor: Sensor, reading: Reading) -> IngestOutcome:
    """Another request stored the same key in the meantime: treat it like a repeat."""
    existing = await uow.measurements.get(sensor.id, reading.measured_at)
    if existing is None:
        raise ConflictError("Повторите запрос")
    return _repeat(existing, reading)


def _repeat(existing: Measurement, reading: Reading) -> IngestOutcome:
    if existing.same_reading(reading):
        return IngestOutcome.DUPLICATE
    raise ConflictError("Для этого времени измерения уже сохранено другое значение")
