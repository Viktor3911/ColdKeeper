"""``coldkeeper-sim``: load history, run the live demo program, inspect scenarios and generated series."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from backend.simulator import devices as device_files
from backend.simulator.generator import derive_seed, generate
from backend.simulator.model import PROFILES
from backend.simulator.runner import run_live, send_history
from backend.simulator.scenarios import SCENARIOS, build_timeline
from backend.simulator.transport import UnitXTransport

logger = logging.getLogger("coldkeeper.simulator")
DEFAULT_URL = "http://localhost:8000"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="coldkeeper-sim", description="Симулятор UnitX для демонстрации ColdKeeper")
    parser.add_argument("--devices", type=Path, default=Path(".demo/devices.json"), help="файл от seed-demo")
    commands = parser.add_subparsers(dest="command", required=True)

    history = commands.add_parser("history", help="ускоренно отправить историю (только прошедшее время)")
    history.add_argument("--url", default=DEFAULT_URL, help="адрес сервера (публичный вход ingest)")
    history.add_argument("--concurrency", type=int, default=16)

    live = commands.add_parser("live", help="живой поток всех датчиков по демо-программе")
    live.add_argument("--url", default=DEFAULT_URL)
    live.add_argument(
        "--scenario",
        action="append",
        default=[],
        metavar="HW=NAME",
        help="заменить сценарий датчика, например demo-fridge-1=sustained_excursion",
    )
    live.add_argument("--only", action="append", default=[], metavar="HW", help="запустить только эти датчики")

    commands.add_parser("scenarios", help="список сценариев")

    preview = commands.add_parser("preview", help="показать сгенерированный ряд без отправки")
    preview.add_argument("--profile", choices=sorted(PROFILES), default="refrigerator")
    preview.add_argument("--scenario", choices=sorted(SCENARIOS), default="normal")
    preview.add_argument("--seed", type=int, default=1)
    preview.add_argument("--start", default="2026-01-01T00:00:00+00:00", help="ISO 8601 с часовым поясом")
    preview.add_argument("--minutes", type=int, default=60)
    preview.add_argument("--step", type=int, default=60, help="шаг в секундах")
    return parser


def _overrides(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        hardware_id, _, scenario = value.partition("=")
        if scenario not in SCENARIOS:
            msg = f"неизвестный сценарий {scenario!r}; см. coldkeeper-sim scenarios"
            raise SystemExit(msg)
        result[hardware_id] = scenario
    return result


async def _history(args: argparse.Namespace) -> int:
    file = device_files.load(args.devices)
    async with httpx.AsyncClient(timeout=10) as client:
        transport = UnitXTransport(client, args.url)
        report = await send_history(file, transport.send, concurrency=args.concurrency)
    logger.info("история отправлена: %s", report.summary())
    return 0


async def _live(args: argparse.Namespace) -> int:
    file = device_files.load(args.devices)
    overrides = _overrides(args.scenario)
    unknown = (set(overrides) | set(args.only)) - {device.hardware_id for device in file.devices}
    if unknown:
        msg = f"нет таких датчиков в {args.devices}: {', '.join(sorted(unknown))}"
        raise SystemExit(msg)
    async with httpx.AsyncClient(timeout=10) as client:
        transport = UnitXTransport(client, args.url)
        await run_live(file, transport.send, overrides=overrides, only=set(args.only) or None)
    return 0


def _scenarios() -> int:
    for scenario in SCENARIOS.values():
        sys.stdout.write(f"{scenario.name:22} {scenario.title}\n")
    return 0


def _preview(args: argparse.Namespace) -> int:
    start = datetime.fromisoformat(args.start).astimezone(UTC)
    end = start + timedelta(minutes=args.minutes)
    timeline = build_timeline([(SCENARIOS[args.scenario], start, start, end)])
    samples = generate(
        PROFILES[args.profile],
        timeline,
        seed=derive_seed(args.seed, "preview"),
        start=start,
        step=timedelta(seconds=args.step),
        duration=end - start,
    )
    for sample in samples:
        value = "null" if sample.temperature is None else f"{sample.temperature:.1f}"
        sent = "" if sample.delivered else "  (нет связи — не отправляется)"
        sys.stdout.write(f"{sample.measured_at.isoformat()}  t={value:>6}  ok={str(sample.ok).lower()}{sent}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Request logs of httpx would print the device token from the URL.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    args = _parser().parse_args(argv)
    try:
        match args.command:
            case "history":
                return asyncio.run(_history(args))
            case "live":
                return asyncio.run(_live(args))
            case "scenarios":
                return _scenarios()
            case _:
                return _preview(args)
    except KeyboardInterrupt:
        return 0
    except FileNotFoundError as error:
        logger.error("%s", error)
        return 2
