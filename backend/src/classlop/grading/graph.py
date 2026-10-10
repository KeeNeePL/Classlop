import asyncio
import operator
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, TypedDict

from langgraph.graph import START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel

from classlop import items as items_area
from classlop.grading.models import GradedItem, GradedSubmission, Reading
from classlop.grading.pages import pages_of, prepare
from classlop.grading.scoring import Score, score
from classlop.grading.transcription import ItemTranscription, transcribe
from classlop.items import ItemVersion
from classlop.shared import jobs, storage
from classlop.shared.db import sessions

AI_LINE = "Ocena i komentarz przygotowane przez AI; nauczyciel sprawdza je wyrywkowo."
# Nothing to judge, or nothing that may be judged: such Items score 0 with no scoring call.
UNSCORED = ("blank", "unreadable")
CORRECT, BLANK = "poprawnie", "brak rozwiązania"
NOT_READ, WRONG = "nie udało się odczytać rozwiązania", "błędna odpowiedź"
# Fixed Feedback carries no maths, so the text comment shows it; scored Feedback may carry maths.
FIXED_FEEDBACK = (CORRECT, BLANK, NOT_READ, WRONG)

Rule = tuple[str, Callable[[GradedItem], bool]]
HELD_REASONS: list[Rule] = [
    ("nieczytelne", lambda i: i.reading == "unreadable"),
    ("niepewny odczyt", lambda i: i.reading == "unsure"),
    ("wątpliwa ocena", lambda i: i.doubt),
]
FLAG_REASONS: list[Rule] = [("rysunek", lambda i: i.drawing)]


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
    # The Held reason when the files cannot be transcribed at all.
    file_problem: str | None
    transcriptions: dict[int, ItemTranscription]
    scores: Annotated[dict[int, Score], operator.or_]
    graded: GradedSubmission


class ScoreTask(TypedDict):
    number: int
    item: ItemVersion
    transcription: str


async def load(state: State) -> dict:
    job = state["job"]
    versions = await items_area.get_versions([i.id for i in job.items])
    files = await asyncio.gather(*(asyncio.to_thread(storage.get, key) for key in job.files))
    items = [(a.number, v) for a, v in zip(job.items, versions, strict=True)]
    pages, problem = pages_of(files)
    return {"items": items, "pages": [prepare(p) for p in pages], "file_problem": problem}


def to_transcription(state: State) -> str:
    return "hold" if state["file_problem"] else "transcribe_pages"


async def hold(state: State) -> dict:
    """Files that cannot be transcribed are not graded at all: the Teacher sees why."""
    job, held = state["job"], [{"reason": state["file_problem"], "items": []}]
    return {
        "graded": GradedSubmission(
            submission_id=job.submission_id,
            handed_in_at=job.handed_in_at,
            status="graded",
            held_reasons=held,
            spot_check_reasons=held,
            comment="",
            items=[],
        )
    }


async def transcribe_pages(state: State) -> dict:
    return {"transcriptions": await transcribe(state["items"], state["pages"])}


def _reading(item: ItemVersion, transcription: ItemTranscription | None) -> Reading:
    # An Item the model left out of its reply is unsure, not blank.
    if transcription is None:
        return "unsure"
    closed_unchosen = (
        item.item_format == "closed" and transcription.chosen_option not in item.options
    )
    if transcription.reading == "readable" and closed_unchosen:
        return "unsure"
    return transcription.reading


def to_scoring(state: State) -> list[Send] | str:
    """One parallel scoring call per open Item with work to judge."""
    transcriptions = state["transcriptions"]
    tasks = [
        Send("score_item", ScoreTask(number=n, item=item, transcription=t.transcription))
        for n, item in state["items"]
        if item.item_format == "open"
        and (t := transcriptions.get(n))
        and _reading(item, t) not in UNSCORED
    ]
    return tasks or "assess"


async def score_item(state: ScoreTask) -> dict:
    return {"scores": {state["number"]: await score(state["item"], state["transcription"])}}


def _grade_item(
    position: int,
    number: int,
    item: ItemVersion,
    transcription: ItemTranscription | None,
    scored: Score | None,
) -> GradedItem:
    reading = _reading(item, transcription)
    if item.item_format == "closed":
        chosen = transcription.chosen_option if transcription else None
        right = reading not in UNSCORED and [chosen] == item.correct_options
        points = item.points if right else 0
    else:
        points = min(max(scored.points, 0), item.points) if scored else 0
    if reading == "blank":
        feedback = BLANK
    elif reading == "unreadable" or transcription is None:
        feedback = NOT_READ
    elif points == item.points:
        feedback = CORRECT
    else:
        feedback = scored.feedback if scored else WRONG
    return GradedItem(
        item_id=item.id,
        position=position,
        number=number,
        max_points=item.points,
        ai_points=points,
        reading=reading,
        drawing=transcription.drawing if transcription else False,
        # Points out of range, or points lost without Feedback: the model went wrong.
        doubt=scored is not None
        and (scored.doubt or scored.points != points or not feedback.strip()),
        ai_transcription=transcription.transcription
        if transcription and reading != "blank"
        else "",
        feedback=feedback,
        mistake=scored.mistake if scored and points < item.points else None,
    )


def _line(item: GradedItem) -> str:
    line = f"Zadanie {item.number}: {item.ai_points}/{item.max_points} pkt"
    return f"{line} – {item.feedback}" if item.feedback in FIXED_FEEDBACK else line


def _reasons(items: list[GradedItem], rules: list[Rule]) -> list[dict]:
    return [
        {"reason": reason, "items": numbers}
        for reason, applies in rules
        if (numbers := [i.number for i in items if applies(i)])
    ]


async def assess(state: State) -> dict:
    job, transcriptions, scores = state["job"], state["transcriptions"], state.get("scores", {})
    graded = [
        _grade_item(position, n, item, transcriptions.get(n), scores.get(n))
        for position, (n, item) in enumerate(state["items"])
    ]
    held = _reasons(graded, HELD_REASONS)
    return {
        "graded": GradedSubmission(
            submission_id=job.submission_id,
            handed_in_at=job.handed_in_at,
            status="graded",
            held_reasons=held,
            spot_check_reasons=held + _reasons(graded, FLAG_REASONS),
            comment="\n".join(_line(i) for i in graded) + f"\n\n{AI_LINE}",
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
    .add_node(load)
    .add_node(transcribe_pages)
    .add_node(score_item)
    .add_node(hold)
    .add_sequence([assess, persist])
    .add_edge(START, "load")
    .add_conditional_edges("load", to_transcription, ["transcribe_pages", "hold"])
    .add_conditional_edges("transcribe_pages", to_scoring, ["score_item", "assess"])
    .add_edge("score_item", "assess")
    .add_edge("hold", "persist")
    .compile()
)
