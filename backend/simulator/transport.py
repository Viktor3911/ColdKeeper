"""Sends samples in the UnitX HTTP push format through the public ingest endpoint."""

from __future__ import annotations

import asyncio
import enum
from dataclasses import dataclass

import httpx

from backend.simulator.generator import Sample

INGEST_PATH = "/api/v1/ingest/unitx"
_RETRIES = 3


class Outcome(enum.StrEnum):
    """Result of one send."""

    ACCEPTED = "accepted"  # 204 (also an identical repeat)
    CONFLICT = "conflict"  # 409: another value is stored for this time
    REJECTED = "rejected"  # other 4xx: configuration problem, like a device would report
    FAILED = "failed"  # network or 5xx after retries


@dataclass(frozen=True, slots=True)
class SendResult:
    """Outcome and HTTP status (0 when no response)."""

    outcome: Outcome
    status: int
    detail: str = ""


def unitx_body(hardware_id: str, sample: Sample) -> dict[str, object]:
    """``{"id", "ts", "t", "ok"}`` exactly as UnitX-T sends it (no ``rh``)."""
    return {
        "id": hardware_id,
        "ts": int(sample.measured_at.timestamp()),
        "t": sample.temperature,
        "ok": sample.ok,
    }


class UnitXTransport:
    """HTTP client with a few retries for temporary errors (the device retries with growing delays too)."""

    def __init__(self, client: httpx.AsyncClient, base_url: str) -> None:
        self._client = client
        self._url = base_url.rstrip("/") + INGEST_PATH

    async def send(self, hardware_id: str, token: str, sample: Sample) -> SendResult:
        """POST one sample; the token goes into the URL like in the device settings."""
        body = unitx_body(hardware_id, sample)
        for attempt in range(_RETRIES):
            try:
                response = await self._client.post(self._url, params={"token": token}, json=body)
            except httpx.TransportError as error:
                result = SendResult(Outcome.FAILED, 0, type(error).__name__)
            else:
                if response.status_code == httpx.codes.NO_CONTENT:
                    return SendResult(Outcome.ACCEPTED, response.status_code)
                if response.status_code == httpx.codes.CONFLICT:
                    return SendResult(Outcome.CONFLICT, response.status_code, _detail(response))
                if response.status_code < httpx.codes.INTERNAL_SERVER_ERROR:
                    return SendResult(Outcome.REJECTED, response.status_code, _detail(response))
                result = SendResult(Outcome.FAILED, response.status_code, _detail(response))
            await asyncio.sleep(0.5 * 2**attempt)
        return result


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:200]
    return str(data.get("detail", ""))[:200] if isinstance(data, dict) else ""
