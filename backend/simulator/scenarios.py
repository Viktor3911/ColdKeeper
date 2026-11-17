"""Named scenarios (event schedules) and the concrete timeline the generator follows."""

from __future__ import annotations

import enum
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta


class EventKind(enum.StrEnum):
    """What can happen to a simulated point."""

    DOOR_OPEN = "door_open"  # short temperature spike
    COMPRESSOR_FAILURE = "compressor_failure"  # sustained rise, recovery when it ends
    LINK_LOSS = "link_loss"  # nothing is sent
    PROBE_FAILURE = "probe_failure"  # ok=false, t=null


@dataclass(frozen=True, slots=True)
class Event:
    """An event ``start`` after the scenario anchor, lasting ``duration``, repeated ``every`` (or once)."""

    kind: EventKind
    start: timedelta
    duration: timedelta
    every: timedelta | None = None


@dataclass(frozen=True, slots=True)
class Scenario:
    """A named schedule of events."""

    name: str
    title: str
    events: tuple[Event, ...] = ()


def _minutes(value: float) -> timedelta:
    return timedelta(minutes=value)


SCENARIOS: dict[str, Scenario] = {
    scenario.name: scenario
    for scenario in (
        Scenario("normal", "Норма: только цикл охлаждения и шум"),
        Scenario(
            "door_spikes",
            "Короткий скачок: дверь открыта на минуту каждые 20 минут (тревога не подтверждается)",
            (Event(EventKind.DOOR_OPEN, _minutes(4), _minutes(1), _minutes(20)),),
        ),
        Scenario(
            "sustained_excursion",
            "Устойчивое превышение: отказ компрессора на 30 минут, затем восстановление; повтор через 75 минут",
            (Event(EventKind.COMPRESSOR_FAILURE, _minutes(3), _minutes(30), _minutes(75)),),
        ),
        Scenario(
            "door_left_open",
            "Тревога по команде: дверь открыта 8 минут сразу после запуска, компрессор не справляется; один раз",
            (
                Event(EventKind.DOOR_OPEN, _minutes(0), _minutes(8)),
                Event(EventKind.COMPRESSOR_FAILURE, _minutes(0), _minutes(8)),
            ),
        ),
        Scenario(
            "connection_loss",
            "Пропажа связи: 8 минут без отправки, повтор каждые 40 минут",
            (Event(EventKind.LINK_LOSS, _minutes(5), _minutes(8), _minutes(40)),),
        ),
        Scenario(
            "probe_failure",
            "Отказ зонда: 4 минуты ok=false без температуры, повтор каждые 40 минут",
            (Event(EventKind.PROBE_FAILURE, _minutes(5), _minutes(4), _minutes(40)),),
        ),
        Scenario(
            "routine_week",
            "История: двери несколько раз в день, один отказ компрессора, один отказ зонда",
            (
                Event(EventKind.DOOR_OPEN, _minutes(50), _minutes(1), timedelta(hours=4)),
                Event(EventKind.COMPRESSOR_FAILURE, timedelta(days=2, hours=14), _minutes(50)),
                Event(EventKind.PROBE_FAILURE, timedelta(days=4, hours=9), _minutes(20)),
            ),
        ),
        Scenario(
            "routine_week_gaps",
            "История с пропуском: как routine_week и почти сутки без связи",
            (
                Event(EventKind.DOOR_OPEN, _minutes(80), _minutes(1), timedelta(hours=5)),
                Event(EventKind.COMPRESSOR_FAILURE, timedelta(days=1, hours=20), _minutes(40)),
                Event(EventKind.LINK_LOSS, timedelta(days=4, hours=22), timedelta(hours=26)),
            ),
        ),
    )
}


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    """An event rule placed in time: active within ``[window_start, window_end)`` on its own schedule.

    Repeats are computed arithmetically, so an endless live run costs the same as a short one.
    """

    kind: EventKind
    first_start: datetime
    duration: timedelta
    every: timedelta | None
    window_start: datetime
    window_end: datetime

    def active(self, moment: datetime) -> bool:
        """Whether this event covers ``moment``."""
        if not self.window_start <= moment < self.window_end or moment < self.first_start:
            return False
        offset = moment - self.first_start
        if self.every is not None:
            offset %= self.every
        return offset < self.duration


@dataclass(frozen=True, slots=True)
class Timeline:
    """Scheduled events of one device; queried by the generator for every sample."""

    events: tuple[ScheduledEvent, ...]

    def active(self, kind: EventKind, moment: datetime) -> bool:
        """Whether an event of this kind covers ``moment``."""
        return any(event.kind is kind and event.active(moment) for event in self.events)


def build_timeline(parts: Iterable[tuple[Scenario, datetime, datetime, datetime]]) -> Timeline:
    """Combine ``(scenario, anchor, from, until)`` parts; events only count inside ``[from, until)``."""
    return Timeline(
        tuple(
            ScheduledEvent(event.kind, anchor + event.start, event.duration, event.every, start, until)
            for scenario, anchor, start, until in parts
            for event in scenario.events
        ),
    )
