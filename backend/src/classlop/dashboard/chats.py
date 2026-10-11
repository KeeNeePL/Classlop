"""Classlop AI tab: the Teacher's Chats. A message goes in as a form (text, perhaps a file) and the
AI's replies stream back as server-sent events while the graph runs; the jobs it starts follow on
the event stream and are read here as job cards."""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from classlop import items
from classlop.dashboard import auth

router = APIRouter(prefix="/api/chats", dependencies=[Depends(auth.teacher)])

MAX_UPLOAD = 25 * 1024 * 1024


class NewChat(BaseModel):
    name: str | None = None


class ChatRename(BaseModel):
    name: str


class ChatEntry(items.Chat):
    # Jobs of the Chat still queued or running: the list badges them.
    running: int = 0


class NumberedItem(BaseModel):
    # The number the Teacher counts the Chat's Items by ("zrób trzecie łatwiejsze").
    number: int
    item: items.Item


class JobCard(items.ChatJob):
    items: list[NumberedItem]


class Chats(Protocol):
    """What the tab needs of `items`; tests and the Playwright server swap it."""

    async def entries(self) -> list[ChatEntry]: ...
    async def create(self, name: str | None) -> items.Chat: ...
    async def get(self, chat_id: str) -> items.Chat: ...
    async def rename(self, chat_id: str, name: str) -> None: ...
    async def delete(self, chat_id: str) -> None: ...
    async def messages(self, chat_id: str) -> list[items.ChatMessage]: ...
    async def jobs(self, chat_id: str) -> list[JobCard]: ...
    def turn(
        self, chat_id: str, text: str, file: tuple[str, bytes] | None
    ) -> AsyncIterator[items.Reply]: ...
    async def upload_anyway(self, pending_id: uuid.UUID) -> None: ...
    async def drop_duplicate(self, pending_id: uuid.UUID) -> None: ...


class ItemsChats:
    async def entries(self) -> list[ChatEntry]:
        running = await items.running_jobs()
        return [
            ChatEntry(**c.model_dump(), running=running.get(c.id, 0)) for c in await items.chats()
        ]

    async def create(self, name: str | None) -> items.Chat:
        return await items.create_chat(name)

    async def get(self, chat_id: str) -> items.Chat:
        return await items.get_chat(chat_id)

    async def rename(self, chat_id: str, name: str) -> None:
        await items.rename_chat(chat_id, name)

    async def delete(self, chat_id: str) -> None:
        await items.delete_chat(chat_id)

    async def messages(self, chat_id: str) -> list[items.ChatMessage]:
        return await items.chat_messages(chat_id)

    async def jobs(self, chat_id: str) -> list[JobCard]:
        numbers = {i: n for n, i in enumerate(await items.chat_item_ids(chat_id), 1)}
        cards = []
        for job in await items.chat_jobs(chat_id):
            added = await items.get_items(job.item_ids)
            cards.append(
                JobCard(
                    **job.model_dump(),
                    items=[
                        NumberedItem(number=numbers[i.id], item=i) for i in added if i.id in numbers
                    ],
                )
            )
        return cards

    def turn(
        self, chat_id: str, text: str, file: tuple[str, bytes] | None
    ) -> AsyncIterator[items.Reply]:
        return items.take_turn(chat_id, text, file)

    async def upload_anyway(self, pending_id: uuid.UUID) -> None:
        await items.upload_anyway(pending_id)

    async def drop_duplicate(self, pending_id: uuid.UUID) -> None:
        await items.drop_duplicate(pending_id)


def backend() -> Chats:
    return ItemsChats()


TheChats = Annotated[Chats, Depends(backend)]


async def known(chat_id: str, chats: TheChats) -> str:
    try:
        await chats.get(chat_id)
    except LookupError:
        raise HTTPException(404, "Nie ma takiego czatu.") from None
    return chat_id


Known = Annotated[str, Depends(known)]


@router.get("")
async def chats(chats: TheChats) -> list[ChatEntry]:
    return await chats.entries()


@router.post("", status_code=201)
async def create(chats: TheChats, body: NewChat | None = None) -> items.Chat:
    return await chats.create(body.name if body else None)


@router.patch("/{chat_id}")
async def rename(chat_id: Known, body: ChatRename, chats: TheChats) -> None:
    try:
        await chats.rename(chat_id, body.name)
    except ValueError as error:
        raise HTTPException(422, "Czat potrzebuje nazwy.") from error


@router.delete("/{chat_id}", status_code=204)
async def delete(chat_id: Known, chats: TheChats) -> None:
    await chats.delete(chat_id)


@router.get("/{chat_id}/messages")
async def messages(chat_id: Known, chats: TheChats) -> list[items.ChatMessage]:
    return await chats.messages(chat_id)


@router.get("/{chat_id}/jobs")
async def jobs(chat_id: Known, chats: TheChats) -> list[JobCard]:
    """The Chat's jobs with the Items they added, oldest first."""
    return await chats.jobs(chat_id)


@router.post("/duplicates/{pending_id}/upload", status_code=204)
async def upload_anyway(pending_id: uuid.UUID, chats: TheChats) -> None:
    """ "Wgraj mimo to": the near-duplicate becomes an Item."""
    try:
        await chats.upload_anyway(pending_id)
    except LookupError:
        raise HTTPException(404, "Tego zadania nie ma już na liście.") from None


@router.post("/duplicates/{pending_id}/drop", status_code=204)
async def drop_duplicate(pending_id: uuid.UUID, chats: TheChats) -> None:
    """ "Pomiń": the near-duplicate is left out."""
    try:
        await chats.drop_duplicate(pending_id)
    except LookupError:
        raise HTTPException(404, "Tego zadania nie ma już na liście.") from None


def frame(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def stream(
    chats: Chats, chat_id: str, text: str, file: tuple[str, bytes] | None
) -> AsyncIterator[str]:
    try:
        async for reply in chats.turn(chat_id, text, file):
            yield frame("reply", reply.model_dump_json())
    except Exception:
        yield frame("failed", "{}")
        raise
    yield frame("done", "{}")


@router.post("/{chat_id}/messages")
async def say(
    chat_id: Known,
    chats: TheChats,
    text: Annotated[str, Form()] = "",
    file: Annotated[UploadFile | None, File()] = None,
) -> StreamingResponse:
    attached = None
    if file is not None and file.filename:
        data = await file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Plik jest za duży.")
        attached = (file.filename, data)
    if not text.strip() and attached is None:
        raise HTTPException(422, "Pusta wiadomość.")
    return StreamingResponse(
        stream(chats, chat_id, text, attached),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
