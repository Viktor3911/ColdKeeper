"""Live status of a measurement point and the rules that open and close incidents.

Pure functions: the caller passes the current state, the settings and the time, and gets back the new state
and the incident transitions. Ingest calls :func:`apply_reading` for fresh readings; the worker calls
:func:`apply_silence` on a timer. Late readings never reach these functions.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from backend.domain.equipment import PointSettings


class PointStatus(enum.StrEnum):
    """What the interface shows for a point, most severe first in :data:`STATUS_SEVERITY`."""

    NO_DATA = "no_data"  # nothing received since installation
    NORMAL = "normal"
    PENDING = "pending"  # out of range, waiting for confirmation
    ALARM = "alarm"  # confirmed temperature deviation
    SENSOR_ERROR = "sensor_error"
    OFFLINE = "offline"


STATUS_SEVERITY: dict[PointStatus, int] = {
    PointStatus.OFFLINE: 5,
    PointStatus.ALARM: 4,
    PointStatus.SENSOR_ERROR: 3,
    PointStatus.PENDING: 2,
    PointStatus.NO_DATA: 1,
    PointStatus.NORMAL: 0,
}


class Direction(enum.StrEnum):
    """Side of the allowed range."""

    HIGH = "high"
    LOW = "low"


class IncidentType(enum.StrEnum):
    """At most one open incident of each type per point."""

    TEMPERATURE = "temperature"
    SENSOR_ERROR = "sensor_error"
    CONNECTION_LOST = "connection_lost"


@dataclass(frozen=True, slots=True)
class IncidentOpened:
    """A new incident should be stored and announced."""

    type: IncidentType
    at: datetime
    direction: Direction | None = None
    temperature: float | None = None


@dataclass(frozen=True, slots=True)
class IncidentClosed:
    """The open incident of this type should be closed and the recovery announced."""

    type: IncidentType
    at: datetime
    temperature: float | None = None


Transition = IncidentOpened | IncidentClosed


@dataclass(frozen=True, slots=True)
class PointState:
    """Everything the rules remember about a point between readings."""

    point_id: UUID
    last_measured_at: datetime | None = None
    last_received_at: datetime | None = None
    last_temperature: float | None = None
    last_sensor_ok: bool | None = None
    deviation_since: datetime | None = None
    deviation_direction: Direction | None = None
    normal_since: datetime | None = None
    temperature_alarm: Direction | None = None
    sensor_error: bool = False
    offline: bool = False

    @property
    def status(self) -> PointStatus:
        """Single status for the interface; the most severe condition wins."""
        if self.offline:
            return PointStatus.OFFLINE
        if self.temperature_alarm is not None:
            return PointStatus.ALARM
        if self.sensor_error:
            return PointStatus.SENSOR_ERROR
        if self.deviation_since is not None:
            return PointStatus.PENDING
        if self.last_measured_at is None:
            return PointStatus.NO_DATA
        return PointStatus.NORMAL


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Result of applying an event to a point state."""

    state: PointState
    transitions: tuple[Transition, ...] = field(default_factory=tuple)


def is_live(state: PointState, settings: PointSettings, measured_at: datetime, now: datetime) -> bool:
    """A reading changes the live status only if it is newer than the last one and arrived on time.

    The same rule applies to devices and the simulator; history loaded later is stored but stays "late".
    """
    if state.last_measured_at is not None and measured_at <= state.last_measured_at:
        return False
    return now - measured_at <= settings.late_threshold


def classify(temperature: float, settings: PointSettings) -> Direction | None:
    """Which side of the range a temperature is on; the thresholds themselves are allowed."""
    if temperature > settings.high_threshold:
        return Direction.HIGH
    if temperature < settings.low_threshold:
        return Direction.LOW
    return None


def apply_reading(
    state: PointState,
    settings: PointSettings,
    *,
    measured_at: datetime,
    received_at: datetime,
    temperature: float | None,
    sensor_ok: bool,
) -> Evaluation:
    """Apply a fresh reading (see :func:`is_live`) to the point state."""
    transitions: list[Transition] = []
    continuous = state.last_measured_at is not None and measured_at - state.last_measured_at <= settings.gap_limit

    if state.offline:
        transitions.append(IncidentClosed(IncidentType.CONNECTION_LOST, measured_at, temperature))
    base = replace(
        state,
        offline=False,
        last_measured_at=measured_at,
        last_received_at=received_at,
        last_temperature=temperature,
        last_sensor_ok=sensor_ok,
    )

    if not sensor_ok or temperature is None:
        if not state.sensor_error:
            transitions.append(IncidentOpened(IncidentType.SENSOR_ERROR, measured_at))
        # An unknown temperature neither confirms a deviation nor a recovery.
        new_state = replace(base, sensor_error=True, deviation_since=None, deviation_direction=None, normal_since=None)
        return Evaluation(new_state, tuple(transitions))

    if state.sensor_error:
        transitions.append(IncidentClosed(IncidentType.SENSOR_ERROR, measured_at, temperature))
        continuous = False  # the error interrupted the series
    base = replace(base, sensor_error=False)

    direction = classify(temperature, settings)
    if direction is None:
        new_state = _apply_normal(base, settings, measured_at, temperature, continuous=continuous, out=transitions)
    else:
        new_state = _apply_deviation(base, settings, measured_at, temperature, direction, continuous, transitions)
    return Evaluation(new_state, tuple(transitions))


def _apply_normal(
    state: PointState,
    settings: PointSettings,
    measured_at: datetime,
    temperature: float,
    *,
    continuous: bool,
    out: list[Transition],
) -> PointState:
    # A normal value resets any unconfirmed deviation.
    state = replace(state, deviation_since=None, deviation_direction=None)
    if state.temperature_alarm is None:
        return replace(state, normal_since=None)
    normal_since = state.normal_since if continuous and state.normal_since is not None else measured_at
    if measured_at - normal_since >= settings.recovery_duration:
        out.append(IncidentClosed(IncidentType.TEMPERATURE, measured_at, temperature))
        return replace(state, temperature_alarm=None, normal_since=None)
    return replace(state, normal_since=normal_since)


def _apply_deviation(
    state: PointState,
    settings: PointSettings,
    measured_at: datetime,
    temperature: float,
    direction: Direction,
    continuous: bool,
    out: list[Transition],
) -> PointState:
    state = replace(state, normal_since=None)
    if state.temperature_alarm is direction:
        return replace(state, deviation_since=None, deviation_direction=None)
    if state.temperature_alarm is not None:
        # Jumped straight to the other side: the old incident ends, the new side must be confirmed again.
        out.append(IncidentClosed(IncidentType.TEMPERATURE, measured_at, temperature))
        state = replace(state, temperature_alarm=None)
        continuous = False

    same_series = continuous and state.deviation_since is not None and state.deviation_direction is direction
    since = state.deviation_since if same_series and state.deviation_since is not None else measured_at
    if measured_at - since >= settings.deviation_duration:
        out.append(IncidentOpened(IncidentType.TEMPERATURE, measured_at, direction, temperature))
        return replace(state, temperature_alarm=direction, deviation_since=None, deviation_direction=None)
    return replace(state, deviation_since=since, deviation_direction=direction)


def apply_silence(state: PointState, settings: PointSettings, now: datetime) -> Evaluation:
    """Detect a lost connection: nothing received for longer than the offline timeout.

    A point that never reported stays "no data" (installation in progress) without an incident.
    """
    if state.offline or state.last_received_at is None:
        return Evaluation(state)
    if now - state.last_received_at <= settings.offline_timeout:
        return Evaluation(state)
    # Missing readings do not prove the temperature stayed out of range, nor that it recovered:
    # an unconfirmed deviation is dropped, an open alarm stays open.
    new_state = replace(state, offline=True, deviation_since=None, deviation_direction=None, normal_since=None)
    return Evaluation(new_state, (IncidentOpened(IncidentType.CONNECTION_LOST, now),))
