"""Telegram start commands for one-time codes and the optional public demo."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

logger = logging.getLogger(__name__)

ConfirmBinding = Callable[[str, int, str], Awaitable[str]]
"""``(code, chat_id, chat_title) -> reply text``; provided by the application."""
DemoSubscription = Callable[[int, str], Awaitable[str]]

_HELP = "Чтобы получать уведомления ColdKeeper, откройте ссылку из настроек получателей или отправьте /start <код>."


def build_dispatcher(confirm: ConfirmBinding, subscribe_demo: DemoSubscription | None = None) -> Dispatcher:
    """Dispatcher with the only handler the bot needs."""
    router = Router(name="coldkeeper-binding")

    @router.message(CommandStart())
    async def _start(message: Message, command: CommandObject) -> None:
        title = message.chat.title or message.chat.full_name or str(message.chat.id)
        if command.args:
            reply = await confirm(command.args, message.chat.id, title)
        elif subscribe_demo is not None and message.chat.type == "private":
            reply = await subscribe_demo(message.chat.id, title)
        else:
            reply = _HELP
        await message.answer(reply)

    @router.message()
    async def _help(message: Message) -> None:
        if subscribe_demo is not None and message.chat.type == "private":
            await message.answer("Чтобы получать уведомления демо-кафе «Север», отправьте /start.")
        else:
            await message.answer(_HELP)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def poll_bindings(bot: Bot, confirm: ConfirmBinding, subscribe_demo: DemoSubscription | None = None) -> None:
    """Run until cancelled. Telegram allows one poller per bot token: run a single worker instance."""
    dispatcher = build_dispatcher(confirm, subscribe_demo)
    logger.info("telegram: polling for binding codes")
    await dispatcher.start_polling(bot, handle_signals=False, close_bot_session=False)
