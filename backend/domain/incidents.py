"""Stored incidents and notification events/deliveries."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from backend.domain.monitoring import Direction, IncidentType


@dataclass(frozen=True, slots=True)
class Incident:
    """An open or closed incident of a point."""

    id: UUID
    organization_id: UUID
    point_id: UUID
    type: IncidentType
    direction: Direction | None
    opened_at: datetime
    closed_at: datetime | None
    open_temperature: float | None
    close_temperature: float | None


class EventKind(enum.StrEnum):
    """Notification is sent when an incident opens and when it closes, never per measurement."""

    OPENED = "opened"
    CLOSED = "closed"


class DeliveryStatus(enum.StrEnum):
    """State of one message to one recipient."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"  # attempts exhausted or a permanent error
    DRY_RUN = "dry_run"  # no bot configured: recorded, not sent


@dataclass(frozen=True, slots=True)
class NotificationEvent:
    """A notification about an incident; stored even when there is nobody to deliver it to."""

    id: UUID
    organization_id: UUID
    incident_id: UUID
    kind: EventKind
    text: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Delivery:
    """One attempt series to deliver an event to one recipient."""

    id: UUID
    event_id: UUID
    recipient_id: UUID
    chat_id: int
    text: str
    status: DeliveryStatus
    attempts: int
    next_attempt_at: datetime
    last_error: str | None


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded retries with a growing pause; Telegram's ``retry_after`` wins when it is longer."""

    delays: tuple[timedelta, ...] = (
        timedelta(seconds=30),
        timedelta(minutes=1),
        timedelta(minutes=2),
        timedelta(minutes=5),
        timedelta(minutes=10),
    )

    @property
    def max_attempts(self) -> int:
        """First try plus one retry per delay."""
        return len(self.delays) + 1

    def next_attempt(self, attempts_made: int, now: datetime, retry_after: timedelta | None) -> datetime | None:
        """Time of the next attempt, or ``None`` when the delivery should be marked failed."""
        if attempts_made >= self.max_attempts:
            return None
        delay = self.delays[attempts_made - 1]
        if retry_after is not None and retry_after > delay:
            delay = retry_after
        return now + delay


@dataclass(frozen=True, slots=True)
class Recipient:
    """A Telegram chat bound to an organization with a one-time code."""

    id: UUID
    organization_id: UUID
    chat_id: int
    title: str
    is_active: bool
    created_at: datetime
