"""Scenario-driven temperature model: a thermostat cycle, bounded noise and a fast door disturbance.

A plausible demo signal, not a physical model of a specific refrigerator:

* the cabinet relaxes exponentially towards the room temperature while the compressor is off and towards the
  evaporator temperature while it is on; a thermostat with hysteresis switches it, giving a smooth cooling cycle;
* an open door adds a fast first-order offset to the air temperature that disappears soon after closing;
* a compressor failure keeps it off, so the temperature drifts up until the failure ends;
* measurement noise is Gaussian with a hard clip and the value is rounded to 0.1 °C like UnitX.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThermalProfile:
    """Parameters of one kind of equipment (temperatures in °C, time constants in seconds)."""

    name: str
    setpoint: float
    hysteresis: float
    room: float
    evaporator: float
    warm_tau: float
    cool_tau: float
    door_offset: float
    door_rise_tau: float = 60.0
    door_fall_tau: float = 90.0
    noise_sigma: float = 0.08
    noise_clip: float = 0.25


PROFILES: dict[str, ThermalProfile] = {
    profile.name: profile
    for profile in (
        ThermalProfile(
            name="refrigerator",
            setpoint=4.0,
            hysteresis=1.0,
            room=24.0,
            evaporator=-8.0,
            warm_tau=120 * 60,
            cool_tau=25 * 60,
            door_offset=5.0,
        ),
        ThermalProfile(
            name="freezer",
            setpoint=-19.0,
            hysteresis=1.5,
            room=22.0,
            evaporator=-32.0,
            warm_tau=180 * 60,
            cool_tau=30 * 60,
            door_offset=4.0,
        ),
    )
}


@dataclass(frozen=True, slots=True)
class ThermalState:
    """Model state between steps."""

    cabinet: float
    compressor_on: bool
    door_offset: float = 0.0


def initial_state(profile: ThermalProfile, rng: random.Random) -> ThermalState:
    """Random point inside the thermostat band (reproducible through ``rng``)."""
    cabinet = profile.setpoint + rng.uniform(-profile.hysteresis, profile.hysteresis)
    return ThermalState(cabinet=cabinet, compressor_on=rng.random() < 0.5)


def _relax(value: float, target: float, seconds: float, tau: float) -> float:
    return target + (value - target) * math.exp(-seconds / tau)


def advance(
    state: ThermalState,
    profile: ThermalProfile,
    seconds: float,
    *,
    door_open: bool,
    compressor_failed: bool,
) -> ThermalState:
    """Integrate ``seconds`` in sub-steps of at most 10 s (analytic exponential within a sub-step)."""
    steps = max(1, math.ceil(seconds / 10))
    dt = seconds / steps
    for _ in range(steps):
        running = state.compressor_on and not compressor_failed
        target, tau = (profile.evaporator, profile.cool_tau) if running else (profile.room, profile.warm_tau)
        cabinet = _relax(state.cabinet, target, dt, tau)
        door_target, door_tau = (
            (profile.door_offset, profile.door_rise_tau) if door_open else (0.0, profile.door_fall_tau)
        )
        door = _relax(state.door_offset, door_target, dt, door_tau)
        # The thermostat reacts to the air temperature, like a cabinet controller does.
        air = cabinet + door
        if compressor_failed:
            compressor_on = False
        elif air >= profile.setpoint + profile.hysteresis:
            compressor_on = True
        elif air <= profile.setpoint - profile.hysteresis:
            compressor_on = False
        else:
            compressor_on = state.compressor_on
        state = ThermalState(cabinet=cabinet, compressor_on=compressor_on, door_offset=door)
    return state


def measure(state: ThermalState, profile: ThermalProfile, rng: random.Random) -> float:
    """Air temperature with clipped noise, rounded like the device."""
    noise = max(-profile.noise_clip, min(profile.noise_clip, rng.gauss(0.0, profile.noise_sigma)))
    return round(state.cabinet + state.door_offset + noise, 1)
