"""Telegram recipients of the organization."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from backend.interfaces.http.dependencies import ContainerDep, ReaderDep, WriterDep
from backend.interfaces.http.schemas import BindingCodeOut, RecipientActiveIn, RecipientOut, RecipientsOut

router = APIRouter(prefix="/api/v1/recipients", tags=["recipients"])


@router.get("")
async def recipients(container: ContainerDep, actor: ReaderDep) -> RecipientsOut:
    """Recipients and whether a bot is configured (otherwise notifications are dry-run)."""
    service = container.recipients
    return RecipientsOut(
        bot_configured=service.bot_configured,
        bot_username=service.bot_username,
        recipients=[RecipientOut.of(item) for item in await service.list_recipients(actor)],
    )


@router.post("/code", status_code=status.HTTP_201_CREATED)
async def binding_code(container: ContainerDep, actor: WriterDep) -> BindingCodeOut:
    """One-time code to send to the bot."""
    code = await container.recipients.new_code(actor)
    return BindingCodeOut(code=code.code, expires_at=code.expires_at, deep_link=code.deep_link)


@router.post("/{recipient_id}/active", status_code=status.HTTP_204_NO_CONTENT)
async def set_active(
    recipient_id: UUID, body: RecipientActiveIn, container: ContainerDep, actor: WriterDep
) -> Response:
    """Pause or resume notifications to a chat."""
    await container.recipients.set_active(actor, recipient_id, active=body.active)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
