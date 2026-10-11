"""Chats and their messages. The Chat graph (turns, streaming) builds on these tables."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import delete, select, update
from ulid import ULID

from classlop.items.models import ChatMessageRow, ChatRow, ItemRow
from classlop.shared.db import sessions

DEFAULT_NAME = "Nowy czat"
NAME_LENGTH = 40


class Chat(BaseModel):
    id: str
    name: str
    created_at: datetime


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


async def create_chat(name: str | None = None) -> Chat:
    async with sessions().begin() as session:
        row = ChatRow(id=str(ULID()), name=name or DEFAULT_NAME)
        session.add(row)
        await session.flush()
        await session.refresh(row)
        return Chat.model_validate(row, from_attributes=True)


async def get_chat(chat_id: str) -> Chat:
    async with sessions()() as session:
        row = await session.get(ChatRow, chat_id)
        if row is None:
            raise LookupError(f"no Chat {chat_id}")
        return Chat.model_validate(row, from_attributes=True)


async def chats() -> list[Chat]:
    """Newest first."""
    async with sessions()() as session:
        rows = await session.scalars(
            select(ChatRow).order_by(ChatRow.created_at.desc(), ChatRow.id.desc())
        )
        return [Chat.model_validate(r, from_attributes=True) for r in rows]


async def rename_chat(chat_id: str, name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("a Chat needs a name")
    async with sessions().begin() as session:
        found = await session.scalar(
            update(ChatRow).where(ChatRow.id == chat_id).values(name=name).returning(ChatRow.id)
        )
        if found is None:
            raise LookupError(f"no Chat {chat_id}")


async def name_after(chat_id: str, text: str) -> None:
    """The first message names a Chat the Teacher has not named."""
    name = " ".join(text.split())[:NAME_LENGTH].strip()
    if name:
        async with sessions().begin() as session:
            await session.execute(
                update(ChatRow)
                .where(ChatRow.id == chat_id, ChatRow.name == DEFAULT_NAME)
                .values(name=name)
            )


async def forget_chat(chat_id: str) -> None:
    """The Chat and its messages; its Items stay in the bank."""
    async with sessions().begin() as session:
        await session.execute(delete(ChatMessageRow).where(ChatMessageRow.chat_id == chat_id))
        await session.execute(delete(ChatRow).where(ChatRow.id == chat_id))


async def chat_item_ids(chat_id: str) -> list[uuid.UUID]:
    """The Chat's Items, oldest first: the order "the third" counts in. Retired Items keep their
    place, so a number never moves."""
    async with sessions()() as session:
        return list(
            await session.scalars(
                select(ItemRow.id)
                .where(ItemRow.origin.in_(("chat", "upload")), ItemRow.origin_ref == chat_id)
                .order_by(ItemRow.created_at, ItemRow.id)
            )
        )
