"""Telegram recipients, binding codes, notification events and the delivery queue."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.db.models import BindingCodeRow, DeliveryRow, NotificationEventRow, RecipientRow
from backend.application.views import DeliveryView, EventView
from backend.domain.incidents import Delivery, DeliveryStatus, EventKind, NotificationEvent, Recipient


def _recipient(row: RecipientRow) -> Recipient:
    return Recipient(
        id=row.id,
        organization_id=row.organization_id,
        chat_id=row.chat_id,
        title=row.title,
        is_active=row.is_active,
        created_at=row.created_at,
    )


class SqlRecipientRepository:
    """:class:`backend.application.ports.RecipientRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def active(self, organization_id: UUID) -> list[Recipient]:
        """Recipients who get notifications."""
        rows = await self._session.scalars(
            select(RecipientRow).where(
                RecipientRow.organization_id == organization_id, RecipientRow.is_active.is_(True)
            ),
        )
        return [_recipient(row) for row in rows]

    async def all_of(self, organization_id: UUID) -> list[Recipient]:
        """All recipients."""
        rows = await self._session.scalars(
            select(RecipientRow)
            .where(RecipientRow.organization_id == organization_id)
            .order_by(RecipientRow.created_at),
        )
        return [_recipient(row) for row in rows]

    async def get_by_chat(self, organization_id: UUID, chat_id: int) -> Recipient | None:
        """By chat."""
        row = await self._session.scalar(
            select(RecipientRow).where(
                RecipientRow.organization_id == organization_id, RecipientRow.chat_id == chat_id
            ),
        )
        return None if row is None else _recipient(row)

    async def save(self, recipient: Recipient) -> None:
        """Upsert by id."""
        await self._session.merge(
            RecipientRow(
                id=recipient.id,
                organization_id=recipient.organization_id,
                chat_id=recipient.chat_id,
                title=recipient.title,
                is_active=recipient.is_active,
                created_at=recipient.created_at,
            ),
        )
        await self._session.flush()

    async def add_code(self, organization_id: UUID, code_hash: str, expires_at: datetime) -> None:
        """Store a code hash."""
        self._session.add(BindingCodeRow(code_hash=code_hash, organization_id=organization_id, expires_at=expires_at))
        await self._session.flush()

    async def consume_code(self, code_hash: str, now: datetime) -> UUID | None:
        """Atomically mark a valid code as used."""
        statement = (
            update(BindingCodeRow)
            .where(
                BindingCodeRow.code_hash == code_hash, BindingCodeRow.used_at.is_(None), BindingCodeRow.expires_at > now
            )
            .values(used_at=now)
            .returning(BindingCodeRow.organization_id)
        )
        organization_id: UUID | None = await self._session.scalar(statement)
        return organization_id


class SqlNotificationRepository:
    """:class:`backend.application.ports.NotificationRepository` on PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_event(self, event: NotificationEvent, deliveries: Sequence[Delivery]) -> None:
        """Event and its deliveries in the caller's transaction."""
        self._session.add(
            NotificationEventRow(
                id=event.id,
                organization_id=event.organization_id,
                incident_id=event.incident_id,
                kind=event.kind.value,
                text=event.text,
                created_at=event.created_at,
            ),
        )
        await self._session.flush()
        self._session.add_all(
            DeliveryRow(
                id=delivery.id,
                event_id=delivery.event_id,
                recipient_id=delivery.recipient_id,
                chat_id=delivery.chat_id,
                text=delivery.text,
                status=delivery.status.value,
                attempts=delivery.attempts,
                next_attempt_at=delivery.next_attempt_at,
                last_error=delivery.last_error,
                updated_at=event.created_at,
            )
            for delivery in deliveries
        )
        await self._session.flush()

    async def claim_due(self, now: datetime) -> Delivery | None:
        """Oldest due delivery, locked; other workers skip it."""
        row = await self._session.scalar(
            select(DeliveryRow)
            .where(DeliveryRow.status == DeliveryStatus.PENDING.value, DeliveryRow.next_attempt_at <= now)
            .order_by(DeliveryRow.next_attempt_at)
            .limit(1)
            .with_for_update(skip_locked=True),
        )
        if row is None:
            return None
        return Delivery(
            id=row.id,
            event_id=row.event_id,
            recipient_id=row.recipient_id,
            chat_id=row.chat_id,
            text=row.text,
            status=DeliveryStatus(row.status),
            attempts=row.attempts,
            next_attempt_at=row.next_attempt_at,
            last_error=row.last_error,
        )

    async def update_delivery(
        self,
        delivery_id: UUID,
        *,
        status: DeliveryStatus,
        attempts: int,
        next_attempt_at: datetime,
        last_error: str | None,
        moment: datetime,
    ) -> None:
        """Outcome of an attempt."""
        await self._session.execute(
            update(DeliveryRow)
            .where(DeliveryRow.id == delivery_id)
            .values(
                status=status.value,
                attempts=attempts,
                next_attempt_at=next_attempt_at,
                last_error=last_error,
                updated_at=moment,
            ),
        )

    async def events_for(self, incident_ids: Sequence[UUID]) -> dict[UUID, list[EventView]]:
        """Events with deliveries."""
        if not incident_ids:
            return {}
        events = list(
            await self._session.scalars(
                select(NotificationEventRow)
                .where(NotificationEventRow.incident_id.in_(incident_ids))
                .order_by(NotificationEventRow.created_at),
            ),
        )
        deliveries: dict[UUID, list[DeliveryView]] = defaultdict(list)
        if events:
            result = await self._session.execute(
                select(DeliveryRow, RecipientRow.title)
                .join(RecipientRow, DeliveryRow.recipient_id == RecipientRow.id)
                .where(DeliveryRow.event_id.in_([event.id for event in events])),
            )
            for delivery, title in result.tuples():
                deliveries[delivery.event_id].append(_delivery_view(delivery, title))
        grouped: dict[UUID, list[EventView]] = defaultdict(list)
        for event in events:
            grouped[event.incident_id].append(
                EventView(
                    kind=EventKind(event.kind),
                    text=event.text,
                    created_at=event.created_at,
                    deliveries=deliveries.get(event.id, []),
                ),
            )
        return dict(grouped)


def _delivery_view(row: DeliveryRow, title: str) -> DeliveryView:
    return DeliveryView(
        recipient_title=title,
        status=DeliveryStatus(row.status),
        attempts=row.attempts,
        last_error=row.last_error,
    )
