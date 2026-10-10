import asyncio
import uuid
from datetime import datetime
from typing import TypedDict

from langgraph.graph import START, StateGraph
from pydantic import BaseModel

from classlop import items as items_area
from classlop.grading.models import GradedItem, GradedSubmission
from classlop.grading.transcription import ItemTranscription, prepare, transcribe
from classlop.items import ItemVersion
from classlop.shared import jobs, storage
from classlop.shared.db import sessions

AI_LINE = "Ocena i komentarz przygotowane przez AI; nauczyciel sprawdza je wyrywkowo."
HELD_REASONS = {"unreadable": "nieczytelne", "unsure": "niepewny odczyt"}


class AssignedItem(BaseModel):
    id: uuid.UUID
    number: int


class GradeJob(BaseModel):
    """The `grading.grade` payload `teams` enqueues on a hand-in."""

    submission_id: uuid.UUID
    handed_in_at: datetime
    items: list[AssignedItem]
    files: list[str]


class Input(TypedDict):
    job: GradeJob


class State(Input):
    items: list[tuple[int, ItemVersion]]
    pages: list[bytes]
    transcriptions: dict[int, ItemTranscription]
    graded: GradedSubmission


async def load(state: State) -> dict:
    job = state["job"]
    versions = await items_area.get_versions([i.id for i in job.items])
    photos = await asyncio.gather(*(asyncio.to_thread(storage.get, key) for key in job.files))
    return {
        "items": [(a.number, v) for a, v in zip(job.items, versions, strict=True)],
        "pages": [prepare(p) for p in photos],
    }


async def transcribe_pages(state: State) -> dict:
    return {"transcriptions": await transcribe(state["items"], state["pages"])}


def _grade_item(position: int, number: int, item: ItemVersion, t: ItemTranscription | None):
    # An Item the model left out of its reply is unsure, not blank.
    reading = t.reading if t else "unsure"
    chosen = t.chosen_option if t else None
    if reading == "readable" and chosen not in item.options:
        reading = "unsure"
    right = reading not in ("blank", "unreadable") and [chosen] == item.correct_options
    return GradedItem(
        item_id=item.id,
        position=position,
        number=number,
        max_points=item.points,
        ai_points=item.points if right else 0,
        reading=reading,
        drawing=t.drawing if t else False,
        ai_transcription=t.transcription if t and reading != "blank" else "",
    )


def _remark(item: GradedItem) -> str:
    if item.reading == "blank":
        return "brak rozwiązania"
    if item.reading == "unreadable":
        return "nie udało się odczytać rozwiązania"
    return "poprawnie" if item.ai_points == item.max_points else "błędna odpowiedź"


async def assess(state: State) -> dict:
    job, transcriptions = state["job"], state["transcriptions"]
    graded = [
        _grade_item(position, number, item, transcriptions.get(number))
        for position, (number, item) in enumerate(state["items"])
    ]
    held = [
        {"reason": reason, "items": [i.number for i in graded if i.reading == reading]}
        for reading, reason in HELD_REASONS.items()
        if any(i.reading == reading for i in graded)
    ]
    lines = [f"Zadanie {i.number}: {i.ai_points}/{i.max_points} pkt – {_remark(i)}" for i in graded]
    return {
        "graded": GradedSubmission(
            submission_id=job.submission_id,
            handed_in_at=job.handed_in_at,
            status="graded",
            held_reasons=held,
            spot_check_reasons=held,
            comment="\n".join(lines) + f"\n\n{AI_LINE}",
            items=graded,
        )
    }


async def persist(state: State) -> dict:
    async with sessions().begin() as session:
        session.add(state["graded"])
    job = state["job"]
    await jobs.enqueue(
        "teams.submission_graded",
        {"submission_id": str(job.submission_id), "handed_in_at": job.handed_in_at.isoformat()},
    )
    return {}


grade_graph = (
    StateGraph(State, input_schema=Input)
    .add_sequence([load, transcribe_pages, assess, persist])
    .add_edge(START, "load")
    .compile()
)
