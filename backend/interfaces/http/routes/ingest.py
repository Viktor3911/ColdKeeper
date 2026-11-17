"""Public ingest endpoint for UnitX HTTP push (and the simulator, which uses exactly the same contract)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import ValidationError

from backend.adapters.unitx.payload import MAX_BODY_BYTES, UnitXPayload, to_reading
from backend.interfaces.http.dependencies import ContainerDep
from backend.interfaces.http.schemas import ErrorOut

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"])


@router.post(
    "/unitx",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        400: {"model": ErrorOut, "description": "Не JSON"},
        401: {"model": ErrorOut, "description": "Неверный или отозванный ключ"},
        403: {"model": ErrorOut, "description": "Аппаратный ID не соответствует ключу"},
        409: {"model": ErrorOut, "description": "Для этого времени уже сохранено другое значение"},
        413: {"model": ErrorOut, "description": "Слишком большой запрос"},
        422: {"model": ErrorOut, "description": "Некорректное измерение"},
    },
)
async def ingest_unitx(
    request: Request,
    container: ContainerDep,
    token: Annotated[str, Query(min_length=20, max_length=200, description="Ключ устройства")],
    rssi: Annotated[int | None, Query(ge=-150, le=0)] = None,
) -> Response:
    """Store one measurement. ``204`` only after the transaction is committed; identical repeats also get ``204``."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Слишком большой запрос")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Слишком большой запрос")
    try:
        payload = UnitXPayload.model_validate_json(body)
    except ValidationError as error:
        is_json = all(item["type"] != "json_invalid" for item in error.errors())
        code = status.HTTP_422_UNPROCESSABLE_CONTENT if is_json else status.HTTP_400_BAD_REQUEST
        raise HTTPException(code, _describe(error)) from None
    await container.ingest(token, to_reading(payload, rssi))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _describe(error: ValidationError) -> str:
    """Field names and reasons only — the request body is never echoed back."""
    parts = [f"{'.'.join(str(loc) for loc in item['loc']) or 'body'}: {item['msg']}" for item in error.errors()[:5]]
    return "Некорректное измерение: " + "; ".join(parts)
