"""Turns monitoring transitions into stored incidents and notification events (inside the caller's transaction)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from backend.application.notification_text import incident_message
from backend.application.ports import UnitOfWork
from backend.domain.equipment import PointLocation
from backend.domain.incidents import Delivery, DeliveryStatus, EventKind, Incident, NotificationEvent
from backend.domain.monitoring import IncidentClosed, IncidentOpened, Transition


class IncidentRecorder:
    """Stores incidents and queues one event per transition with a delivery per active recipient."""

    async def record(
        self,
        uow: UnitOfWork,
        location: PointLocation,
        transitions: Sequence[Transition],
        now: datetime,
    ) -> None:
        """Apply transitions produced by :mod:`backend.domain.monitoring`."""
        for transition in transitions:
            if isinstance(transition, IncidentOpened):
                await self._opened(uow, location, transition, now)
            else:
                await self._closed(uow, location, transition, now)

    async def _opened(self, uow: UnitOfWork, location: PointLocation, opened: IncidentOpened, now: datetime) -> None:
        incident = Incident(
            id=uuid.uuid4(),
            organization_id=location.organization_id,
            point_id=location.point_id,
            type=opened.type,
            direction=opened.direction,
            opened_at=opened.at,
            closed_at=None,
            open_temperature=opened.temperature,
            close_temperature=None,
        )
        # The partial unique index keeps one open incident per type even if two processes race.
        if await uow.incidents.open(incident):
            await self._queue(uow, location, incident, EventKind.OPENED, now)

    async def _closed(self, uow: UnitOfWork, location: PointLocation, closed: IncidentClosed, now: datetime) -> None:
        incident = await uow.incidents.get_open(location.point_id, closed.type)
        if incident is None:
            return
        await uow.incidents.close(incident.id, closed.at, closed.temperature)
        finished = Incident(
            id=incident.id,
            organization_id=incident.organization_id,
            point_id=incident.point_id,
            type=incident.type,
            direction=incident.direction,
            opened_at=incident.opened_at,
            closed_at=closed.at,
            open_temperature=incident.open_temperature,
            close_temperature=closed.temperature,
        )
        await self._queue(uow, location, finished, EventKind.CLOSED, now)

    async def _queue(
        self,
        uow: UnitOfWork,
        location: PointLocation,
        incident: Incident,
        kind: EventKind,
        now: datetime,
    ) -> None:
        text = incident_message(location, incident, kind)
        event = NotificationEvent(
            id=uuid.uuid4(),
            organization_id=location.organization_id,
            incident_id=incident.id,
            kind=kind,
            text=text,
            created_at=now,
        )
        recipients = await uow.recipients.active(location.organization_id)
        deliveries = [
            Delivery(
                id=uuid.uuid4(),
                event_id=event.id,
                recipient_id=recipient.id,
                chat_id=recipient.chat_id,
                text=text,
                status=DeliveryStatus.PENDING,
                attempts=0,
                next_attempt_at=now,
                last_error=None,
            )
            for recipient in recipients
        ]
        await uow.notifications.add_event(event, deliveries)
