"""Classlop AI tab: the Teacher's Chats. A message goes in as a form (text, perhaps a file) and the
AI's replies stream back as server-sent events while the graph runs."""

from collections.abc import AsyncIterator
from typing import Annotated

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


async def known(chat_id: str) -> str:
    try:
        await items.get_chat(chat_id)
    except LookupError:
        raise HTTPException(404, "Nie ma takiego czatu.") from None
    return chat_id


Known = Annotated[str, Depends(known)]


@router.get("")
async def chats() -> list[items.Chat]:
    return await items.chats()


@router.post("", status_code=201)
async def create(body: NewChat | None = None) -> items.Chat:
    return await items.create_chat(body.name if body else None)


@router.patch("/{chat_id}")
async def rename(chat_id: Known, body: ChatRename) -> None:
    try:
        await items.rename_chat(chat_id, body.name)
    except ValueError as error:
        raise HTTPException(422, "Czat potrzebuje nazwy.") from error


@router.delete("/{chat_id}", status_code=204)
async def delete(chat_id: Known) -> None:
    await items.delete_chat(chat_id)


@router.get("/{chat_id}/messages")
async def messages(chat_id: Known) -> list[items.ChatMessage]:
    return await items.chat_messages(chat_id)


def frame(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


async def stream(chat_id: str, text: str, file: tuple[str, bytes] | None) -> AsyncIterator[str]:
    try:
        async for reply in items.take_turn(chat_id, text, file):
            yield frame("reply", reply.model_dump_json())
    except Exception:
        yield frame("failed", "{}")
        raise
    yield frame("done", "{}")


@router.post("/{chat_id}/messages")
async def say(
    chat_id: Known,
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
        stream(chat_id, text, attached),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
