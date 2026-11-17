"""Notification senders: aiogram for a configured bot, dry-run otherwise."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
    TelegramUnauthorizedError,
)

from backend.application.ports import DeliveryError

logger = logging.getLogger(__name__)


class TelegramSender:
    """Sends plain-text messages through the Bot API."""

    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    @property
    def is_dry_run(self) -> bool:
        """Messages are really sent."""
        return False

    async def send(self, chat_id: int, text: str) -> None:
        """Map Bot API errors to retryable or permanent failures."""
        try:
            await self._bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
        except TelegramRetryAfter as error:
            raise DeliveryError(
                "Telegram ограничил частоту отправки", retry_after=timedelta(seconds=error.retry_after)
            ) from error
        except (TelegramForbiddenError, TelegramUnauthorizedError) as error:
            raise DeliveryError(f"Бот не может писать в этот чат: {error.message}", permanent=True) from error
        except TelegramBadRequest as error:
            raise DeliveryError(f"Telegram отклонил сообщение: {error.message}", permanent=True) from error
        except (TelegramNetworkError, TelegramServerError) as error:
            raise DeliveryError(f"Временная ошибка Telegram: {error.message}") from error


class DryRunSender:
    """No bot token: deliveries are recorded as dry-run, nothing leaves the server, nothing pretends success."""

    @property
    def is_dry_run(self) -> bool:
        """Nothing is sent."""
        return True

    async def send(self, chat_id: int, text: str) -> None:
        """Log only; the caller marks the delivery as dry-run."""
        logger.info("dry-run: message for chat %s not sent (%d chars)", chat_id, len(text))
