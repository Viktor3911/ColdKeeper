"""Sensor registration, device tokens and assignment to measurement points."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from uuid import UUID

from backend.application.ports import Clock, SecretIssuer, UnitOfWork, UnitOfWorkFactory
from backend.application.views import IssuedToken, SensorView
from backend.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from backend.domain.organizations import Actor
from backend.domain.sensors import Assignment, Sensor, SensorKind, check_hardware_id

_NO_TIME_TRAVEL = timedelta(seconds=1)


class SensorService:
    """Owners register sensors and move them between points without rewriting history."""

    def __init__(self, uow_factory: UnitOfWorkFactory, clock: Clock, secrets: SecretIssuer) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets

    async def list_sensors(self, actor: Actor) -> list[SensorView]:
        """Sensors with their current point and last contact."""
        async with self._uow_factory() as uow:
            sensors = await uow.sensors.for_organization(actor.organization_id)
            return [await self._view(uow, sensor) for sensor in sensors]

    async def get(self, actor: Actor, sensor_id: UUID) -> tuple[SensorView, list[Assignment]]:
        """A sensor with its assignment history."""
        async with self._uow_factory() as uow:
            sensor = await self._sensor(uow, actor, sensor_id)
            return await self._view(uow, sensor), await uow.assignments.for_sensor(sensor.id)

    async def register(self, actor: Actor, hardware_id: str, kind: SensorKind, model: str) -> IssuedToken:
        """Register a device and issue its first token (shown once)."""
        actor.require_owner()
        now = self._clock.now()
        token = self._secrets.new_token()
        sensor = Sensor(
            id=uuid.uuid4(),
            organization_id=actor.organization_id,
            hardware_id=check_hardware_id(hardware_id),
            kind=kind,
            model=model.strip()[:100] or "UnitX-T",
            token_hash=self._secrets.digest(token),
            token_issued_at=now,
            created_at=now,
        )
        async with self._uow_factory() as uow:
            if await uow.sensors.get_by_hardware_id(sensor.hardware_id) is not None:
                raise ConflictError("Датчик с таким аппаратным ID уже зарегистрирован")
            await uow.sensors.add(sensor)
            await uow.commit()
        return IssuedToken(sensor_id=sensor.id, token=token)

    async def issue_token(self, actor: Actor, sensor_id: UUID) -> IssuedToken:
        """Replace the token; the previous one stops working immediately."""
        actor.require_owner()
        token = self._secrets.new_token()
        async with self._uow_factory() as uow:
            sensor = await self._sensor(uow, actor, sensor_id)
            await uow.sensors.set_token(sensor.id, self._secrets.digest(token), self._clock.now())
            await uow.commit()
        return IssuedToken(sensor_id=sensor_id, token=token)

    async def token_matches(self, actor: Actor, sensor_id: UUID, token: str) -> bool:
        """Whether ``token`` is the sensor's current key (lets the demo seed keep working keys)."""
        async with self._uow_factory() as uow:
            sensor = await self._sensor(uow, actor, sensor_id)
        return sensor.token_hash is not None and sensor.token_hash == self._secrets.digest(token)

    async def revoke_token(self, actor: Actor, sensor_id: UUID) -> None:
        """The device can no longer send readings until a new token is issued."""
        actor.require_owner()
        async with self._uow_factory() as uow:
            sensor = await self._sensor(uow, actor, sensor_id)
            await uow.sensors.set_token(sensor.id, None, self._clock.now())
            await uow.commit()

    async def assign(
        self,
        actor: Actor,
        sensor_id: UUID,
        point_id: UUID,
        starts_at: datetime | None = None,
    ) -> Assignment:
        """Make the sensor measure the point from ``starts_at`` (now by default).

        The sensor's previous assignment and the point's previous sensor end at the same moment. The start may not
        precede already stored measurements of either, so no measurement ever moves to another point.
        """
        actor.require_owner()
        now = self._clock.now()
        start = starts_at or now
        if start > now:
            raise ValidationFailedError("Начало привязки не может быть в будущем")
        async with self._uow_factory() as uow:
            sensor = await self._sensor(uow, actor, sensor_id)
            if await uow.inventory.get_point(actor.organization_id, point_id) is None:
                raise NotFoundError("Точка измерения не найдена")
            await self._check_start(uow, sensor.id, point_id, start)
            current = {
                found.id: found
                for found in (
                    await uow.assignments.open_for_sensor(sensor.id),
                    await uow.assignments.open_for_point(point_id),
                )
                if found is not None
            }
            for previous in current.values():
                if previous.starts_at >= start:
                    raise ConflictError("Текущая привязка начинается позже выбранного момента")
                await uow.assignments.close(previous.id, start)
            assignment = Assignment(
                id=uuid.uuid4(),
                sensor_id=sensor.id,
                point_id=point_id,
                starts_at=start,
                ends_at=None,
            )
            await uow.assignments.add(assignment)
            await uow.commit()
        return assignment

    async def unassign(self, actor: Actor, sensor_id: UUID) -> None:
        """End the sensor's current assignment now; its later readings are stored as unassigned."""
        actor.require_owner()
        async with self._uow_factory() as uow:
            sensor = await self._sensor(uow, actor, sensor_id)
            current = await uow.assignments.open_for_sensor(sensor.id)
            if current is None:
                raise ConflictError("Датчик не привязан к точке")
            latest = await uow.measurements.latest_for_sensor(sensor.id)
            end = self._clock.now()
            if latest is not None and latest.measured_at >= end:
                end = latest.measured_at + _NO_TIME_TRAVEL  # a device clock slightly ahead
            await uow.assignments.close(current.id, end)
            await uow.commit()

    @staticmethod
    async def _check_start(uow: UnitOfWork, sensor_id: UUID, point_id: UUID, start: datetime) -> None:
        sensor_latest = await uow.measurements.latest_for_sensor(sensor_id)
        if sensor_latest is not None and sensor_latest.measured_at >= start:
            raise ConflictError("У датчика уже есть измерения после выбранного момента: история не переносится")
        point_latest = await uow.measurements.latest_for_point(point_id)
        if point_latest is not None and point_latest.measured_at >= start:
            raise ConflictError("У точки уже есть измерения после выбранного момента")

    @staticmethod
    async def _sensor(uow: UnitOfWork, actor: Actor, sensor_id: UUID) -> Sensor:
        sensor = await uow.sensors.get(actor.organization_id, sensor_id)
        if sensor is None:
            raise NotFoundError("Датчик не найден")
        return sensor

    @staticmethod
    async def _view(uow: UnitOfWork, sensor: Sensor) -> SensorView:
        assignment = await uow.assignments.open_for_sensor(sensor.id)
        record = None if assignment is None else await uow.inventory.point_record(assignment.point_id)
        latest = await uow.measurements.latest_for_sensor(sensor.id)
        return SensorView(
            sensor=sensor,
            assignment=assignment,
            point=None if record is None else record.location,
            last_measured_at=None if latest is None else latest.measured_at,
            last_temperature=None if latest is None else latest.temperature,
            last_sensor_ok=None if latest is None else latest.sensor_ok,
            last_unassigned=latest is not None and latest.point_id is None,
        )
