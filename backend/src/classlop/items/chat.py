"""The messages of a Chat. The Chat graph (turns, streaming) builds on this table."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from classlop.items.models import ChatMessageRow
from classlop.shared.db import sessions


class ChatMessage(BaseModel):
    id: uuid.UUID
    chat_id: str
    role: Literal["assistant", "user"]
    text: str
    # What the screen renders beside the text, such as an upload summary.
    payload: dict
    created_at: datetime


async def post_message(
    chat_id: str,
    text: str,
    payload: dict | None = None,
    role: Literal["assistant", "user"] = "assistant",
) -> uuid.UUID:
    async with sessions().begin() as session:
        row = ChatMessageRow(chat_id=chat_id, role=role, text=text, payload=payload or {})
        session.add(row)
        await session.flush()
        return row.id


async def chat_messages(chat_id: str) -> list[ChatMessage]:
    """The Chat's messages, oldest first."""
    async with sessions()() as session:
        rows = await session.scalars(
            select(ChatMessageRow)
            .where(ChatMessageRow.chat_id == chat_id)
            .order_by(ChatMessageRow.created_at, ChatMessageRow.id)
        )
        return [ChatMessage.model_validate(r, from_attributes=True) for r in rows]
