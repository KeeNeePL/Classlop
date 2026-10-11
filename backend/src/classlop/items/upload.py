"""The Item upload graph: one worker job per file. The file goes to S3 under
`items/uploads/<upload-id>/`, a split node saves its page images, and one branch per page makes one
vision call that finds the exercises (sub-parts together) and performs the Extraction into LaTeX
with a confidence and a bounding box. The crop is saved beside the file. Each exercise is skipped
with its reason, or completed (answer, Model solution, points, Rubric), tagged and checked for a
near-duplicate: a close one waits as a pending record, any other becomes an Item, Flagged when the
Extraction was unsure. The summary lands in the Chat as a message. Graph state holds ids and
each exercise's outcome, never the content."""

import asyncio
import base64
import io
import json
import operator
import re
import uuid
from datetime import datetime
from typing import Annotated, Literal, TypedDict

import pypdfium2 as pdfium
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete, select

from classlop.items import chat, index, records, tagging
from classlop.items.generation import DUPLICATE_COSINE, Draft
from classlop.items.models import PendingDuplicateRow
from classlop.items.types import ItemContent
from classlop.shared import jobs, llm, storage
from classlop.shared.db import sessions
from classlop.shared.jobs import Progress
from classlop.shared.search import client
from classlop.shared.settings import get_settings

PREFIX = "items/uploads"
LONG_SIDE = 2000
MAX_PAGES = 30
UNSURE_BELOW = 0.7
PARALLEL_PAGES = 3
COMPLETION_ATTEMPTS = 2
UNSURE = "sprawdź tekst zadania"
SKIPPED = {
    "unreadable": "nieczytelne",
    "figure_dependent": "zależne od rysunku",
    "no_basic_topic": "brak tematu z poziomu podstawowego",
    "incomplete": "nie udało się dopisać rozwiązania",
}

READ = """Dostajesz stronę pliku nauczyciela matematyki w liceum: skan, zdjęcie albo PDF.
Znajdź na niej wszystkie zadania. Podpunkty (a, b, c) należą do jednego zadania. Dla każdego:
- label: numer zadania tak, jak jest wydrukowany, albo kolejny numer na stronie.
- text: pełna treść zadania w LaTeX (cała matematyka między znakami $), z opcjami odpowiedzi A-D,
  jeśli są. Niczego nie poprawiaj ani nie rozwiązuj.
- confidence: od 0 do 1, jak pewnie odczytałeś treść (0.5 gdy nie jesteś pewien cyfry, znaku
  albo zapisu).
- box: ramka zadania na stronie [lewo, góra, prawo, dół] jako ułamki szerokości i wysokości.
- skip: null, gdy zadanie da się przyjąć. W przeciwnym razie powód: "unreadable" (nie da się
  odczytać treści), "figure_dependent" (treść wymaga rysunku, którego nie opisano słowami) albo
  "no_basic_topic" (zadanie wykracza poza podstawę programową poziomu podstawowego).
- points, answer, solution: tylko to, co plik sam podaje przy zadaniu (punkty, odpowiedź,
  rozwiązanie); w przeciwnym razie null."""
COMPLETE = """Jesteś autorem zadań z matematyki dla liceum (poziom podstawowy). Dostajesz zadanie
nauczyciela odczytane z pliku. Zwróć je jako zadanie do banku: text bez opcji odpowiedzi, cała
matematyka jako LaTeX w znakach $. Treści nie zmieniaj. Zadanie zamknięte: options (A-D),
correct_options, bez answer i rubric. Zadanie otwarte: answer, model_solution i rubric jako
poziomy punktacji CKE rosnące do points, bez options. Dopisz to, czego brakuje (odpowiedź,
rozwiązanie wzorcowe, punkty, rubrykę). Odpowiedź, rozwiązanie i punkty od nauczyciela zachowaj."""


class Exercise(BaseModel):
    label: str
    text: str
    confidence: float
    box: list[float]
    skip: Literal["unreadable", "figure_dependent", "no_basic_topic"] | None = None
    points: int | None = None
    answer: str | None = None
    solution: str | None = None


class PageReading(BaseModel):
    exercises: list[Exercise]


class Request(BaseModel):
    upload_id: uuid.UUID
    chat_id: str
    filename: str


class Entry(BaseModel):
    """What became of one exercise: an Item, a skip with its reason, or a pending record."""

    kind: Literal["item", "skipped", "pending"]
    page: int
    label: str
    crop: str
    item_id: uuid.UUID | None = None
    flagged: bool = False
    reason: str | None = None
    pending_id: uuid.UUID | None = None
    nearest_item_id: uuid.UUID | None = None


class UploadSummary(BaseModel):
    upload_id: uuid.UUID
    filename: str
    pages: int
    pages_ignored: int
    items: list[Entry]
    skipped: list[Entry]
    pending: list[Entry]


class Started(BaseModel):
    upload_id: uuid.UUID
    job_id: uuid.UUID


class UploadLinks(BaseModel):
    """Short-lived links to the file, the page images and the crops (by file name)."""

    file: str | None
    pages: dict[str, str]
    crops: dict[str, str]


class PendingDuplicate(BaseModel):
    id: uuid.UUID
    upload_id: uuid.UUID
    chat_id: str
    content: ItemContent
    source_page: int
    crop: str
    flag_reason: str | None
    nearest_item_id: uuid.UUID
    cosine: float
    created_at: datetime


class PageInput(TypedDict):
    number: int


class State(TypedDict, total=False):
    pages: int
    ignored: int
    outcomes: Annotated[list[dict], operator.add]
    summary: dict


def _prefix(upload_id: uuid.UUID) -> str:
    return f"{PREFIX}/{upload_id}/"


async def request_upload(chat_id: str, filename: str, data: bytes) -> Started:
    """Keep the file in S3 and queue the job that turns it into Items; the job's result is the
    upload summary."""
    upload_id = uuid.uuid4()
    name = re.sub(r"[^\w.\- ]", "_", filename.replace("\\", "/").rsplit("/", 1)[-1]) or "plik"
    await asyncio.to_thread(
        storage.put, _prefix(upload_id) + name, data, "application/octet-stream"
    )
    job_id = await jobs.enqueue(
        "items.upload",
        Request(upload_id=upload_id, chat_id=chat_id, filename=name).model_dump(mode="json"),
    )
    return Started(upload_id=upload_id, job_id=job_id)


def _split(file: bytes, limit: int) -> list[Image.Image]:
    """At most `limit` pages; none when the file is neither an image nor a PDF. Files are told
    apart by content: phones name and type them unreliably."""
    try:
        if b"%PDF" in file[:1024]:
            pdf = pdfium.PdfDocument(file)
            return [
                pdf[i].render(scale=LONG_SIDE / max(pdf[i].get_size())).to_pil()
                for i in range(min(len(pdf), limit))
            ]
        image = Image.open(io.BytesIO(file))
        image.load()
        return [image]
    except (pdfium.PdfiumError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return []


def _jpeg(page: Image.Image) -> bytes:
    page = ImageOps.exif_transpose(page)
    page.thumbnail((LONG_SIDE, LONG_SIDE))
    out = io.BytesIO()
    page.convert("RGB").save(out, "JPEG", quality=90)
    return out.getvalue()


def _crop(page: Image.Image, box: list[float]) -> bytes:
    """The exercise's part of the page; the whole page when the box is unusable."""
    left, top, right, bottom = (min(max(v, 0.0), 1.0) for v in (box + [0, 0, 1, 1])[:4])
    if right - left < 0.01 or bottom - top < 0.01:
        left, top, right, bottom = 0.0, 0.0, 1.0, 1.0
    w, h = page.size
    return _jpeg(page.crop((int(left * w), int(top * h), int(right * w), int(bottom * h))))


class Run:
    def __init__(self, request: Request, progress: Progress, tagger: tagging.Tagger):
        self.request, self.progress, self.tagger = request, progress, tagger
        self.prefix = _prefix(request.upload_id)
        self.file = self.prefix + request.filename
        self.done = 0
        self._counting = asyncio.Lock()

    async def split(self, state: State) -> dict:
        data = await asyncio.to_thread(storage.get, self.file)
        pages = _split(data, MAX_PAGES + 1)
        ignored = max(len(pages) - MAX_PAGES, 0)
        for n, page in enumerate(pages[:MAX_PAGES], 1):
            await asyncio.to_thread(
                storage.put, f"{self.prefix}pages/{n}.jpg", _jpeg(page), "image/jpeg"
            )
        return {"pages": min(len(pages), MAX_PAGES), "ignored": ignored}

    def fan_out(self, state: State) -> list[Send] | list[str]:
        return [Send("page", PageInput(number=n)) for n in range(1, state.get("pages", 0) + 1)] or [
            "summarize"
        ]

    async def page(self, state: PageInput) -> dict:
        number = state["number"]
        data = await asyncio.to_thread(storage.get, f"{self.prefix}pages/{number}.jpg")
        reading = await llm.ask(
            "items.upload_read",
            PageReading,
            [
                SystemMessage(READ),
                HumanMessage(
                    [
                        {"type": "text", "text": f"Strona {number}"},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": "data:image/jpeg;base64," + base64.b64encode(data).decode()
                            },
                        },
                    ]
                ),
            ],
        )
        image = Image.open(io.BytesIO(data))
        entries = [
            await self.exercise(number, n, exercise, image)
            for n, exercise in enumerate(reading.exercises, 1)
        ]
        async with self._counting:
            self.done += 1
            await self.progress({"pages_done": self.done})
        return {"outcomes": [e.model_dump(mode="json") for e in entries]}

    async def exercise(self, page: int, n: int, exercise: Exercise, image: Image.Image) -> Entry:
        crop = f"p{page}-{n}.jpg"
        await asyncio.to_thread(
            storage.put, f"{self.prefix}crops/{crop}", _crop(image, exercise.box), "image/jpeg"
        )
        entry = Entry(kind="skipped", page=page, label=exercise.label, crop=crop)
        if exercise.skip:
            return entry.model_copy(update={"reason": SKIPPED[exercise.skip]})
        content = await self.complete(exercise)
        if content is None:
            return entry.model_copy(update={"reason": SKIPPED["incomplete"]})
        flag_reason = UNSURE if exercise.confidence < UNSURE_BELOW else None
        nearest = await index.nearest_item(content)
        if nearest and nearest[1] > DUPLICATE_COSINE:
            async with sessions().begin() as session:
                row = PendingDuplicateRow(
                    upload_id=self.request.upload_id,
                    chat_id=self.request.chat_id,
                    content=content.model_dump(mode="json"),
                    source_file=self.file,
                    source_page=page,
                    crop=crop,
                    flag_reason=flag_reason,
                    nearest_item_id=nearest[0],
                    cosine=nearest[1],
                )
                session.add(row)
                await session.flush()
            return entry.model_copy(
                update={"kind": "pending", "pending_id": row.id, "nearest_item_id": nearest[0]}
            )
        item_id = await records.create_item(
            content,
            origin="upload",
            origin_ref=self.request.chat_id,
            source_file=self.file,
            source_page=page,
            flag_reason=flag_reason,
        )
        # Searchable now, so a later exercise of the file is checked against this Item.
        await index.reindex(item_id)
        await client().indices.refresh(index=get_settings().items_index)
        return entry.model_copy(
            update={"kind": "item", "item_id": item_id, "flagged": flag_reason is not None}
        )

    async def complete(self, exercise: Exercise) -> ItemContent | None:
        """The exercise as an Item, with what the file did not give written by the AI; None when
        the AI cannot make a valid Item of it."""
        given = exercise.model_dump(include={"text", "points", "answer", "solution"})
        for _ in range(COMPLETION_ATTEMPTS):
            draft = await llm.ask(
                "items.upload_complete",
                Draft,
                [SystemMessage(COMPLETE), HumanMessage(json.dumps(given, ensure_ascii=False))],
            )
            tags = await self.tagger.tag("\n".join([draft.text, *draft.options.values()]))
            fields = draft.model_dump()
            # The Teacher's own answer, solution and points win over the AI's.
            if exercise.points is not None:
                fields["points"] = exercise.points
            if exercise.solution:
                fields["model_solution"] = exercise.solution
            if exercise.answer and draft.item_format == "open":
                fields["answer"] = exercise.answer
            try:
                return ItemContent.model_validate(
                    fields
                    | {
                        f: getattr(tags, f)
                        for f in ("difficulty", "curriculum_topics", "general_requirements")
                    }
                )
            except ValidationError:
                continue
        return None

    async def summarize(self, state: State) -> dict:
        entries = [Entry.model_validate(o) for o in state.get("outcomes", [])]
        entries.sort(key=lambda e: (e.page, e.crop))
        summary = UploadSummary(
            upload_id=self.request.upload_id,
            filename=self.request.filename,
            pages=state.get("pages", 0),
            pages_ignored=state.get("ignored", 0),
            items=[e for e in entries if e.kind == "item"],
            skipped=[e for e in entries if e.kind == "skipped"],
            pending=[e for e in entries if e.kind == "pending"],
        )
        if not summary.pages:
            text = f"Nie udało się odczytać pliku {summary.filename}."
        else:
            text = (
                f"Plik {summary.filename}: zadań w banku {len(summary.items)} "
                f"(do sprawdzenia {sum(e.flagged for e in summary.items)}), "
                f"pominiętych {len(summary.skipped)}, "
                f"podobnych czeka na decyzję {len(summary.pending)}."
            )
            if summary.pages_ignored:
                text += f" Pominięto {summary.pages_ignored} ostatnich stron."
        payload = summary.model_dump(mode="json")
        await chat.post_message(
            self.request.chat_id, text, {"kind": "upload_summary", "summary": payload}
        )
        return {"summary": payload}

    async def run(self) -> dict:
        graph = (
            StateGraph(State)
            .add_node("split", self.split)
            .add_node("page", self.page)
            .add_node("summarize", self.summarize)
            .add_edge(START, "split")
            .add_conditional_edges("split", self.fan_out, ["page", "summarize"])
            .add_edge("page", "summarize")
            .add_edge("summarize", END)
            .compile()
        )
        end = await graph.ainvoke({"outcomes": []}, {"max_concurrency": PARALLEL_PAGES})
        return end["summary"]


async def upload(request: Request, progress: Progress) -> dict:
    return await Run(request, progress, tagging.default_tagger()).run()


async def upload_links(upload_id: uuid.UUID) -> UploadLinks:
    """Presigned links to the upload's file, page images and crops."""
    prefix = _prefix(upload_id)
    keys = await asyncio.to_thread(storage.list_keys, prefix)

    def under(folder: str) -> dict[str, str]:
        return {
            k.removeprefix(prefix + folder): storage.presigned_url(k)
            for k in keys
            if k.startswith(prefix + folder)
        }

    files = [k for k in keys if "/" not in k.removeprefix(prefix)]
    return UploadLinks(
        file=storage.presigned_url(files[0]) if files else None,
        pages=under("pages/"),
        crops=under("crops/"),
    )


def _pending(row: PendingDuplicateRow) -> PendingDuplicate:
    return PendingDuplicate.model_validate(row, from_attributes=True)


async def pending_duplicates(upload_id: uuid.UUID) -> list[PendingDuplicate]:
    """The upload's near-duplicates still waiting for the Teacher, in page order."""
    async with sessions()() as session:
        rows = await session.scalars(
            select(PendingDuplicateRow)
            .where(PendingDuplicateRow.upload_id == upload_id)
            .order_by(PendingDuplicateRow.source_page, PendingDuplicateRow.crop)
        )
        return [_pending(r) for r in rows]


async def upload_anyway(pending_id: uuid.UUID) -> uuid.UUID:
    """The pending near-duplicate becomes an Item (Flagged if its Extraction was unsure)."""
    async with sessions().begin() as session:
        row = await session.get(PendingDuplicateRow, pending_id, with_for_update=True)
        if row is None:
            raise LookupError(f"no pending near-duplicate {pending_id}")
        item_id = await records._create(
            session,
            ItemContent.model_validate(row.content),
            origin="upload",
            origin_ref=row.chat_id,
            source_file=row.source_file,
            source_page=row.source_page,
            flag_reason=row.flag_reason,
        )
        await session.delete(row)
    await records._reindex(item_id)
    return item_id


async def drop_duplicate(pending_id: uuid.UUID) -> None:
    async with sessions().begin() as session:
        found = await session.scalar(
            delete(PendingDuplicateRow)
            .where(PendingDuplicateRow.id == pending_id)
            .returning(PendingDuplicateRow.id)
        )
    if found is None:
        raise LookupError(f"no pending near-duplicate {pending_id}")
