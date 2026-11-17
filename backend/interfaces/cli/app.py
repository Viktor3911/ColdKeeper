"""``coldkeeper`` administration CLI: organizations, users and demo data (no public sign-up exists)."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import logging
import os
import secrets
import sys
from collections.abc import Callable

from backend.composition import Container, build_container
from backend.domain.errors import ColdKeeperError
from backend.domain.organizations import Role
from backend.interfaces.cli.demo import DemoSeeder
from backend.settings import Environment, Settings

PASSWORD_ENV = "COLDKEEPER_NEW_PASSWORD"  # noqa: S105 - variable name, not a secret


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coldkeeper", description="Администрирование ColdKeeper")
    commands = parser.add_subparsers(dest="command", required=True)

    org = commands.add_parser("create-org", help="создать организацию (клиента)")
    org.add_argument("name")

    user = commands.add_parser("create-user", help="создать пользователя организации")
    user.add_argument("--org", required=True, help="точное название организации")
    user.add_argument("--login", required=True)
    user.add_argument("--role", choices=[role.value for role in Role], default=Role.OWNER.value)
    user.add_argument(
        "--generate-password",
        action="store_true",
        help=f"сгенерировать пароль и показать один раз (иначе — из {PASSWORD_ENV} или запрос в консоли)",
    )

    password = commands.add_parser("set-password", help="сменить пароль пользователя")
    password.add_argument("--login", required=True)
    password.add_argument("--generate-password", action="store_true")

    commands.add_parser("seed-demo", help="создать или обновить демо-данные (не для production)")
    return parser


def _password(generate: bool) -> tuple[str, bool]:
    """Password from generation, the environment or an interactive prompt; ``True`` if it must be shown."""
    if generate:
        return secrets.token_urlsafe(15), True
    from_env = os.environ.get(PASSWORD_ENV)
    if from_env:
        return from_env, False
    first = getpass.getpass("Пароль: ")
    if first != getpass.getpass("Повторите пароль: "):
        msg = "Пароли не совпадают"
        raise SystemExit(msg)
    return first, False


async def _run(container: Container, args: argparse.Namespace) -> list[str]:
    match args.command:
        case "create-org":
            organization = await container.admin.create_organization(args.name)
            return [f"Организация создана: {organization.name} ({organization.id})"]
        case "create-user":
            password, show = _password(args.generate_password)
            user = await container.admin.create_user(args.org, args.login, password, Role(args.role))
            lines = [f"Пользователь создан: {user.login} ({user.role.value})"]
            return [*lines, f"Пароль (показан один раз): {password}"] if show else lines
        case "set-password":
            password, show = _password(args.generate_password)
            await container.admin.set_password(args.login, password)
            return ["Пароль изменён", *([f"Новый пароль: {password}"] if show else [])]
        case _:
            if container.settings.env is Environment.PRODUCTION:
                msg = "seed-demo запрещён при COLDKEEPER_ENV=production"
                raise SystemExit(msg)
            return await DemoSeeder(container, container.settings.demo_dir).run()


async def _main(args: argparse.Namespace, factory: Callable[[Settings], Container]) -> list[str]:
    container = factory(Settings())
    try:
        return await _run(container, args)
    finally:
        await container.close()


def main(argv: list[str] | None = None, factory: Callable[[Settings], Container] = build_container) -> int:
    """Entry point."""
    logging.basicConfig(level=logging.WARNING)
    args = _parser().parse_args(argv)
    try:
        lines = asyncio.run(_main(args, factory))
    except ColdKeeperError as error:
        sys.stderr.write(f"Ошибка: {error.message}\n")
        return 1
    sys.stdout.write("\n".join(lines) + "\n")
    return 0
