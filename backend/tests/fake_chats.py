"""The Classlop AI tab's `Chats` in memory, for tests and for the Playwright server, which run
without a database or a model. It is a fake Chat: a message asking to "wygeneruj" starts an invented
Generation request that lands three Items in the bank one by one; a file starts an invented upload
with one near-duplicate waiting; anything else is answered with a question."""

import asyncio
import uuid
from collections.abc import AsyncIterator, Coroutine
from datetime import UTC, datetime

from fake_bank import InMemoryBank, content
from fake_events import InMemoryFeed

from classlop import items
from classlop.dashboard.chats import ChatEntry, JobCard, NumberedItem
from classlop.dashboard.events import Event
from classlop.items.upload import PendingDuplicate

STEP = 0.4
GENERATED = 3
QUESTION = "Ile zadań, jakiej trudności i w jakim formacie?"


class InMemoryChats:
    def __init__(self, bank: InMemoryBank, feed: InMemoryFeed) -> None:
        self.bank, self.feed = bank, feed
        self.tasks: list[asyncio.Task] = []
        self.reset()

    def reset(self) -> None:
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
        self.chats: dict[str, items.Chat] = {}
        self.said: dict[str, list[items.ChatMessage]] = {}
        self.cards: dict[str, list[JobCard]] = {}
        self.decided: list[tuple[str, uuid.UUID]] = []

    def _say(self, chat_id: str, role: str, text: str, payload: dict | None = None) -> None:
        self.said[chat_id].append(
            items.ChatMessage(
                id=uuid.uuid4(),
                chat_id=chat_id,
                role=role,  # type: ignore[arg-type]
                text=text,
                payload=payload or {},
                created_at=datetime.now(UTC),
            )
        )

    async def entries(self) -> list[ChatEntry]:
        return [
            ChatEntry(
                **c.model_dump(),
                running=sum(j.status == "running" for j in self.cards[c.id]),
            )
            for c in reversed(self.chats.values())
        ]

    async def create(self, name: str | None) -> items.Chat:
        chat = items.Chat(
            id=f"01J{len(self.chats) + 1:023d}",
            name=name or "Nowy czat",
            created_at=datetime.now(UTC),
        )
        self.chats[chat.id] = chat
        self.said[chat.id], self.cards[chat.id] = [], []
        return chat

    async def get(self, chat_id: str) -> items.Chat:
        if chat_id not in self.chats:
            raise LookupError(chat_id)
        return self.chats[chat_id]

    async def rename(self, chat_id: str, name: str) -> None:
        if not name.strip():
            raise ValueError("a Chat needs a name")
        self.chats[chat_id] = self.chats[chat_id].model_copy(update={"name": name.strip()})

    async def delete(self, chat_id: str) -> None:
        for table in (self.chats, self.said, self.cards):
            del table[chat_id]

    async def messages(self, chat_id: str) -> list[items.ChatMessage]:
        return self.said[chat_id]

    async def jobs(self, chat_id: str) -> list[JobCard]:
        """The cards, with their Items as the bank has them now (one may have been retired)."""
        return [
            card.model_copy(
                update={
                    "items": [
                        n.model_copy(update={"item": self.bank.items[n.item.id]})
                        for n in card.items
                    ]
                }
            )
            for card in self.cards[chat_id]
        ]

    async def turn(
        self, chat_id: str, text: str, file: tuple[str, bytes] | None
    ) -> AsyncIterator[items.Reply]:
        if self.chats[chat_id].name == "Nowy czat" and text.strip():
            self.chats[chat_id] = self.chats[chat_id].model_copy(update={"name": text[:40]})
        self._say(chat_id, "user", text, {"file": file[0]} if file else None)
        task: Coroutine | None = None
        if file:
            card = self._card("upload", filename=file[0])
            reply = items.Reply(
                text=f"Przetwarzam plik {file[0]}.", payload={"job_id": str(card.job_id)}
            )
            task = self._upload(chat_id, card)
        elif "wygeneruj" in text.lower():
            card = self._card("generation")
            reply = items.Reply(
                text=f"Zaczynam generować {GENERATED} zadania.",
                payload={"job_id": str(card.job_id)},
            )
            task = self._generate(chat_id, card)
        else:
            reply = items.Reply(text=QUESTION)
        self._say(chat_id, "assistant", reply.text, reply.payload)
        if task:
            self.cards[chat_id].append(card)
            self.tasks.append(asyncio.create_task(task))
        yield reply

    @staticmethod
    def _card(kind: str, **fields) -> JobCard:
        return JobCard(
            job_id=uuid.uuid4(),
            kind=kind,  # type: ignore[arg-type]
            status="running",
            progress=None,
            items=[],
            **fields,
        )

    def _event(self, card: JobCard) -> None:
        self.feed.events.append(
            Event(
                kind=card.kind,
                job_id=str(card.job_id),
                status=card.status,
                progress=card.progress,
                at=datetime.now(UTC),
            )
        )

    def _land(self, card: JobCard, chat_id: str, text: str) -> None:
        added = self.bank.add(content("lo2024:III.4", text=text), chat_id)
        number = sum(len(c.items) for c in self.cards[chat_id]) + 1
        card.items.append(NumberedItem(number=number, item=added))
        card.item_ids.append(added.id)

    async def _generate(self, chat_id: str, card: JobCard) -> None:
        for landed in range(GENERATED):
            card.progress = {"landed": landed, "total": GENERATED}
            self._event(card)
            await asyncio.sleep(STEP)
            self._land(card, chat_id, f"Rozwiąż równanie $x^2 = {landed + 1}$.")
        card.progress = {"landed": GENERATED, "total": GENERATED}
        card.status = "succeeded"
        self._event(card)

    async def _upload(self, chat_id: str, card: JobCard) -> None:
        for done in range(2):
            card.progress = {"pages": 2, "pages_done": done}
            self._event(card)
            await asyncio.sleep(STEP)
        self._land(card, chat_id, r"Oblicz $\sqrt{49}$.")
        card.progress = {"pages": 2, "pages_done": 2}
        card.pending = [
            PendingDuplicate(
                id=uuid.uuid4(),
                upload_id=uuid.uuid4(),
                chat_id=chat_id,
                content=content("lo2024:III.4", text="Rozwiąż równanie $x^2 = 1$."),
                source_page=2,
                crop="2-1.jpg",
                flag_reason=None,
                nearest_item_id=card.item_ids[0],
                cosine=0.95,
                created_at=datetime.now(UTC),
            )
        ]
        card.status = "succeeded"
        self._event(card)

    def _decide(self, pending_id: uuid.UUID, how: str) -> None:
        for cards in self.cards.values():
            for card in cards:
                kept = [p for p in card.pending if p.id != pending_id]
                if len(kept) != len(card.pending):
                    card.pending = kept
                    self.decided.append((how, pending_id))
                    return
        raise LookupError(pending_id)

    async def upload_anyway(self, pending_id: uuid.UUID) -> None:
        self._decide(pending_id, "upload")

    async def drop_duplicate(self, pending_id: uuid.UUID) -> None:
        self._decide(pending_id, "drop")
