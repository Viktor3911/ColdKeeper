"""Telegram recipients, binding codes and the delivery queue processed by the worker."""

from __future__ import annotations

import uuid
from datetime import timedelta
from uuid import UUID

from backend.application.ports import Clock, DeliveryError, NotificationSender, SecretIssuer, UnitOfWorkFactory
from backend.application.views import BindingCode
from backend.domain.equipment import clean_name
from backend.domain.errors import NotFoundError
from backend.domain.incidents import DeliveryStatus, Recipient, RetryPolicy
from backend.domain.organizations import Actor

BINDING_CODE_LIFETIME = timedelta(minutes=15)
MAX_ERROR_LENGTH = 500


class RecipientService:
    """Owners bind chats with a one-time code that the recipient sends to the bot."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        secrets: SecretIssuer,
        bot_username: str | None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._secrets = secrets
        self._bot_username = bot_username

    @property
    def bot_configured(self) -> bool:
        """Whether a real bot is configured (otherwise deliveries are dry-run)."""
        return self._bot_username is not None

    @property
    def bot_username(self) -> str | None:
        """Bot name for instructions in the interface."""
        return self._bot_username

    async def list_recipients(self, actor: Actor) -> list[Recipient]:
        """All recipients of the organization."""
        async with self._uow_factory() as uow:
            return await uow.recipients.all_of(actor.organization_id)

    async def new_code(self, actor: Actor) -> BindingCode:
        """A one-time code valid for 15 minutes, shown once."""
        actor.require_owner()
        code = self._secrets.new_code()
        expires_at = self._clock.now() + BINDING_CODE_LIFETIME
        async with self._uow_factory() as uow:
            await uow.recipients.add_code(actor.organization_id, self._secrets.digest(code), expires_at)
            await uow.commit()
        link = f"https://t.me/{self._bot_username}?start={code}" if self._bot_username else None
        return BindingCode(code=code, expires_at=expires_at, deep_link=link)

    async def set_active(self, actor: Actor, recipient_id: UUID, *, active: bool) -> None:
        """Pause or resume notifications to a chat."""
        actor.require_owner()
        async with self._uow_factory() as uow:
            recipients = {recipient.id: recipient for recipient in await uow.recipients.all_of(actor.organization_id)}
            recipient = recipients.get(recipient_id)
            if recipient is None:
                raise NotFoundError("Получатель не найден")
            await uow.recipients.save(
                Recipient(
                    id=recipient.id,
                    organization_id=recipient.organization_id,
                    chat_id=recipient.chat_id,
                    title=recipient.title,
                    is_active=active,
                    created_at=recipient.created_at,
                ),
            )
            await uow.commit()

    async def confirm(self, code: str, chat_id: int, title: str) -> str:
        """Called by the bot when a chat sends ``/start <code>``; returns the reply text."""
        now = self._clock.now()
        async with self._uow_factory() as uow:
            organization_id = await uow.recipients.consume_code(self._secrets.digest(code.strip()), now)
            if organization_id is None:
                return "Код не найден или устарел. Получите новый код в настройках ColdKeeper."
            organization = await uow.organizations.get(organization_id)
            existing = await uow.recipients.get_by_chat(organization_id, chat_id)
            recipient = Recipient(
                id=existing.id if existing else uuid.uuid4(),
                organization_id=organization_id,
                chat_id=chat_id,
                title=clean_name(title or str(chat_id), "название чата"),
                is_active=True,
                created_at=existing.created_at if existing else now,
            )
            await uow.recipients.save(recipient)
            await uow.commit()
        name = organization.name if organization else "организации"
        return f"Готово: этот чат будет получать уведомления ColdKeeper ({name})."


class DeliverNotifications:
    """Worker step: deliver due messages one by one, with bounded retries and a visible final error."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        clock: Clock,
        sender: NotificationSender,
        policy: RetryPolicy,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._sender = sender
        self._policy = policy

    async def __call__(self, limit: int = 20) -> int:
        """Process up to ``limit`` due deliveries; returns how many were handled."""
        handled = 0
        while handled < limit:
            async with self._uow_factory() as uow:
                delivery = await uow.notifications.claim_due(self._clock.now())
                if delivery is None:
                    return handled
                attempts = delivery.attempts + 1
                status, next_at, error = DeliveryStatus.SENT, self._clock.now(), None
                if self._sender.is_dry_run:
                    status = DeliveryStatus.DRY_RUN
                else:
                    try:
                        await self._sender.send(delivery.chat_id, delivery.text)
                    except DeliveryError as failure:
                        now = self._clock.now()
                        retry_at = (
                            None if failure.permanent else self._policy.next_attempt(attempts, now, failure.retry_after)
                        )
                        status = DeliveryStatus.PENDING if retry_at is not None else DeliveryStatus.FAILED
                        next_at = retry_at or now
                        error = failure.reason[:MAX_ERROR_LENGTH]
                await uow.notifications.update_delivery(
                    delivery.id,
                    status=status,
                    attempts=attempts,
                    next_attempt_at=next_at,
                    last_error=error,
                    moment=self._clock.now(),
                )
                await uow.commit()
            handled += 1
        return handled
