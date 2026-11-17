"""UnitX Wi-Fi HTTP push format and its normalization into the common :class:`Reading`.

Documented body (POST): ``{"id": "utx-ae4634", "ts": 1792711142, "t": 23.6, "rh": 45.3, "ok": true}``;
UnitX-T has no ``rh``. Unknown extra fields are accepted and ignored. The format is specific to UnitX —
another vendor needs its own adapter producing the same :class:`Reading`.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from backend.domain.telemetry import Reading

MAX_BODY_BYTES = 4096
# 2001-09-09 … 2100-01-01: catches seconds-vs-milliseconds mistakes before domain checks.
_MIN_TS = 1_000_000_000
_MAX_TS = 4_102_444_800


class UnitXPayload(BaseModel):
    """One UnitX measurement."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: Annotated[str, Field(min_length=1, max_length=64)]
    ts: Annotated[int, Field(ge=_MIN_TS, le=_MAX_TS, strict=True)]
    t: float | None = None
    ok: StrictBool
    rh: float | None = None

    @field_validator("t", "rh", mode="before")
    @classmethod
    def _numbers_only(cls, value: Any) -> Any:
        """Empty humidity (``""``, as a URL template may produce) means "absent"; booleans and NaN are invalid."""
        if value == "" or value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            msg = "ожидается число"
            raise ValueError(msg)
        if not math.isfinite(value):
            msg = "NaN и бесконечность не допускаются"
            raise ValueError(msg)
        return value


def to_reading(payload: UnitXPayload, rssi: int | None = None) -> Reading:
    """Normalize to UTC/°C. With ``ok=false`` the temperature is unknown even if the device sent a number."""
    return Reading(
        hardware_id=payload.id.strip(),
        measured_at=datetime.fromtimestamp(payload.ts, tz=UTC),
        temperature=payload.t if payload.ok else None,
        sensor_ok=payload.ok,
        humidity=payload.rh,
        rssi=rssi,
    )
