"""Runs device series: accelerated history (past only) and a real-time live stream.

Each device has one continuous series starting at ``history_start`` of the device file. History sends
``[history_start, history_end)`` as fast as the server accepts; live mode fast-forwards the same series and
sends samples when their time comes, so both modes agree and repeated history is idempotent.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from backend.simulator.devices import Device, DeviceFile
from backend.simulator.generator import Sample, derive_seed, generate
from backend.simulator.model import PROFILES
from backend.simulator.scenarios import SCENARIOS, Timeline, build_timeline
from backend.simulator.transport import Outcome, SendResult

logger = logging.getLogger("coldkeeper.simulator")

Clock = Callable[[], datetime]
Sleep = Callable[[float], Awaitable[None]]
Send = Callable[[str, str, Sample], Awaitable[SendResult]]

_FAR_FUTURE = timedelta(days=3650)


def utc_now() -> datetime:
    """Real clock."""
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class Report:
    """Counts of send outcomes."""

    outcomes: Counter[Outcome] = field(default_factory=Counter)
    skipped_link_loss: int = 0

    def add(self, result: SendResult) -> None:
        """Count one result."""
        self.outcomes[result.outcome] += 1

    def summary(self) -> str:
        """One line for the log."""
        parts = [f"{outcome.value}={count}" for outcome, count in sorted(self.outcomes.items())]
        return ", ".join([*parts, f"не отправлено (нет связи)={self.skipped_link_loss}"])


def timeline_for(device: Device, file: DeviceFile, live_from: datetime | None, live_scenario: str | None) -> Timeline:
    """History events before ``history_end``; live events anchored at ``live_from``."""
    parts = [(SCENARIOS[device.history_scenario], file.history_start, file.history_start, file.history_end)]
    if live_from is not None:
        scenario = SCENARIOS[live_scenario or device.live_scenario]
        parts.append((scenario, live_from, live_from, live_from + _FAR_FUTURE))
    return build_timeline(parts)


def series(device: Device, file: DeviceFile, timeline: Timeline) -> Iterator[Sample]:
    """The device's endless series from the common anchor."""
    return generate(
        PROFILES[device.profile],
        timeline,
        seed=derive_seed(file.seed, device.hardware_id),
        start=file.history_start,
        step=timedelta(seconds=file.step_seconds),
    )


async def send_history(file: DeviceFile, send: Send, *, concurrency: int = 16) -> Report:
    """Send the past part of every series; nothing at or after ``history_end`` (never future dates)."""
    report = Report()
    queue: asyncio.Queue[tuple[Device, Sample] | None] = asyncio.Queue(maxsize=concurrency * 4)

    async def worker() -> None:
        while (item := await queue.get()) is not None:
            device, sample = item
            report.add(await send(device.hardware_id, device.token, sample))

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    for device in file.devices:
        for sample in series(device, file, timeline_for(device, file, None, None)):
            if sample.measured_at >= file.history_end:
                break
            if sample.delivered:
                await queue.put((device, sample))
            else:
                report.skipped_link_loss += 1
        logger.info("история %s поставлена в очередь", device.hardware_id)
    for _ in workers:
        await queue.put(None)
    await asyncio.gather(*workers)
    return report


async def run_live_device(
    device: Device,
    file: DeviceFile,
    send: Send,
    *,
    clock: Clock,
    sleep: Sleep,
    launch: datetime,
    live_scenario: str | None = None,
    until: datetime | None = None,
    report: Report | None = None,
) -> None:
    """Send samples in real time from ``launch`` (or ``history_end`` if later) until ``until`` or forever."""
    report = report or Report()
    timeline = timeline_for(device, file, launch, live_scenario)
    first = max(launch, file.history_end)
    for sample in series(device, file, timeline):
        if sample.measured_at < first:
            continue  # fast-forward: the model state still advances
        if until is not None and sample.measured_at >= until:
            return
        delay = (sample.measured_at - clock()).total_seconds()
        if delay > 0:
            await sleep(delay)
        if not sample.delivered:
            report.skipped_link_loss += 1
            continue
        result = await send(device.hardware_id, device.token, sample)
        report.add(result)
        if result.outcome is not Outcome.ACCEPTED:
            logger.warning(
                "%s %s: %s %s", device.hardware_id, sample.measured_at.isoformat(), result.status, result.detail
            )


async def run_live(
    file: DeviceFile,
    send: Send,
    *,
    clock: Clock = utc_now,
    sleep: Sleep = asyncio.sleep,
    overrides: dict[str, str] | None = None,
    only: set[str] | None = None,
) -> None:
    """Demo program: every device with its live scenario (or an override) in parallel."""
    launch = clock().replace(second=0, microsecond=0) + timedelta(minutes=1)
    devices = [device for device in file.devices if only is None or device.hardware_id in only]
    overrides = overrides or {}
    for device in devices:
        scenario = overrides.get(device.hardware_id, device.live_scenario)
        logger.info("%s: сценарий %s — %s", device.hardware_id, scenario, SCENARIOS[scenario].title)
    await asyncio.gather(
        *(
            run_live_device(
                device,
                file,
                send,
                clock=clock,
                sleep=sleep,
                launch=launch,
                live_scenario=overrides.get(device.hardware_id),
            )
            for device in devices
        ),
    )
