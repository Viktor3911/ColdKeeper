"""Pure, reproducible generation of a temperature series: no clock, no sleeping, no HTTP.

The same profile, timeline, seed, start and step always give the same samples (with the Python version
pinned in ``.python-version``: :mod:`random` guarantees the sequence of ``random()``; distributions such as
``gauss`` may change between Python versions).
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.simulator.model import ThermalProfile, advance, initial_state, measure
from backend.simulator.scenarios import EventKind, Timeline


@dataclass(frozen=True, slots=True)
class Sample:
    """One generated measurement; ``delivered=False`` means the link was down and nothing is sent."""

    measured_at: datetime
    temperature: float | None
    ok: bool
    delivered: bool


def derive_seed(base_seed: int, key: str) -> int:
    """Independent stream per device: a stable hash of the common seed and the device id."""
    digest = hashlib.sha256(f"{base_seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def generate(
    profile: ThermalProfile,
    timeline: Timeline,
    *,
    seed: int,
    start: datetime,
    step: timedelta,
    duration: timedelta | None = None,
) -> Iterator[Sample]:
    """Samples at ``start``, ``start + step``, …; endless when ``duration`` is ``None``."""
    if step <= timedelta(0):
        msg = "step must be positive"
        raise ValueError(msg)
    rng = random.Random(seed)
    state = initial_state(profile, rng)
    moment = start
    end = None if duration is None else start + duration
    while end is None or moment < end:
        value = measure(state, profile, rng)
        probe_failed = timeline.active(EventKind.PROBE_FAILURE, moment)
        yield Sample(
            measured_at=moment,
            temperature=None if probe_failed else value,
            ok=not probe_failed,
            delivered=not timeline.active(EventKind.LINK_LOSS, moment),
        )
        state = advance(
            state,
            profile,
            step.total_seconds(),
            door_open=timeline.active(EventKind.DOOR_OPEN, moment),
            compressor_failed=timeline.active(EventKind.COMPRESSOR_FAILURE, moment),
        )
        moment += step
