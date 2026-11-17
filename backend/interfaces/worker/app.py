"""``coldkeeper-worker``: connection-loss checks, notification delivery and Telegram binding codes.

Incidents and the queue live in PostgreSQL, so a restart forgets nothing and creates no duplicates.
Run exactly one instance when a bot token is configured (one long-polling client per token).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot

from backend.adapters.telegram.binding import poll_bindings
from backend.adapters.telegram.senders import DryRunSender, TelegramSender
from backend.application.ports import NotificationSender
from backend.composition import Container, build_container, build_delivery
from backend.interfaces.logging_setup import configure_logging
from backend.settings import Settings

logger = logging.getLogger("backend.worker")


async def every(seconds: float, name: str, step: Callable[[], Awaitable[int]]) -> None:
    """Run ``step`` forever; an error is logged and retried on the next tick instead of stopping the worker."""
    while True:
        try:
            handled = await step()
            if handled:
                logger.info("%s: %d", name, handled)
        except Exception:
            logger.exception("%s failed", name)
        await asyncio.sleep(seconds)


async def run(settings: Settings, container: Container | None = None) -> None:
    """All worker loops until cancelled."""
    container = container or build_container(settings)
    bot: Bot | None = None
    sender: NotificationSender
    if settings.bot_configured and settings.telegram_bot_token is not None:
        bot = Bot(token=settings.telegram_bot_token.get_secret_value())
        sender = TelegramSender(bot)
        logger.info("telegram: bot @%s", settings.telegram_bot_username)
    else:
        sender = DryRunSender()
        logger.info("telegram: bot token not configured — deliveries are recorded as dry-run")
    deliver = build_delivery(container, sender)
    tasks = [
        every(settings.worker_connectivity_seconds, "connection lost", container.check_connectivity),
        every(settings.worker_delivery_seconds, "deliveries", deliver),
    ]
    if bot is not None:
        tasks.append(poll_bindings(bot, container.recipients.confirm))
    try:
        await asyncio.gather(*tasks)
    finally:
        if bot is not None:
            await bot.session.close()
        await container.close()


def main() -> int:
    """Entry point."""
    settings = Settings()
    configure_logging(settings.log_level)
    try:
        asyncio.run(run(settings))
    except KeyboardInterrupt:
        logger.info("worker stopped")
    return 0
