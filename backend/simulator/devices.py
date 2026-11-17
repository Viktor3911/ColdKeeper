"""The device file written by ``coldkeeper seed-demo`` (``.demo/devices.json``, kept out of Git).

The simulator knows only this file and the server URL; it has no database access and no server code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from backend.simulator.model import PROFILES
from backend.simulator.scenarios import SCENARIOS


class Device(BaseModel):
    """One simulated sensor."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    hardware_id: Annotated[str, Field(min_length=1, max_length=64)]
    token: Annotated[str, Field(min_length=20)]
    label: str = ""
    profile: str
    history_scenario: str = "routine_week"
    live_scenario: str = "normal"

    @field_validator("profile")
    @classmethod
    def _known_profile(cls, value: str) -> str:
        if value not in PROFILES:
            msg = f"unknown profile {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("history_scenario", "live_scenario")
    @classmethod
    def _known_scenario(cls, value: str) -> str:
        if value not in SCENARIOS:
            msg = f"unknown scenario {value!r}"
            raise ValueError(msg)
        return value


class DeviceFile(BaseModel):
    """Content of ``devices.json``."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    version: int = 1
    seed: int
    step_seconds: Annotated[int, Field(ge=1, le=3600)] = 60
    history_start: AwareDatetime
    history_end: AwareDatetime
    devices: list[Device]

    def device(self, hardware_id: str) -> Device:
        """By id."""
        for device in self.devices:
            if device.hardware_id == hardware_id:
                return device
        msg = f"device {hardware_id!r} is not in the file"
        raise KeyError(msg)


def load(path: Path) -> DeviceFile:
    """Read and validate the file."""
    if not path.exists():
        msg = f"{path} не найден: сначала выполните `task seed:demo`"
        raise FileNotFoundError(msg)
    return DeviceFile.model_validate_json(path.read_text(encoding="utf-8"))
