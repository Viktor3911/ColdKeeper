"""Long polling for ``/start <code>`` messages that bind a chat to an organization."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

logger = logging.getLogger(__name__)

ConfirmBinding = Callable[[str, int, str], Awaitable[str]]
"""``(code, chat_id, chat_title) -> reply text``; provided by the application."""

_HELP = "Чтобы получать уведомления ColdKeeper, откройте ссылку из настроек получателей или отправьте /start <код>."


def build_dispatcher(confirm: ConfirmBinding) -> Dispatcher:
    """Dispatcher with the only handler the bot needs."""
    router = Router(name="coldkeeper-binding")

    @router.message(CommandStart(deep_link=True))
    async def _start_with_code(message: Message, command: CommandObject) -> None:
        title = message.chat.title or message.chat.full_name or str(message.chat.id)
        reply = await confirm(command.args or "", message.chat.id, title)
        await message.answer(reply)

    @router.message()
    async def _help(message: Message) -> None:
        await message.answer(_HELP)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def poll_bindings(bot: Bot, confirm: ConfirmBinding) -> None:
    """Run until cancelled. Telegram allows one poller per bot token: run a single worker instance."""
    dispatcher = build_dispatcher(confirm)
    logger.info("telegram: polling for binding codes")
    await dispatcher.start_polling(bot, handle_signals=False, close_bot_session=False)
