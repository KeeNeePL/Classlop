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
from classlop.grading.common_mistakes import chosen_option_mistake, request_if_computed
from classlop.grading.models import GradedItem, GradedSubmission, Reading
from classlop.grading.pages import pages_of, prepare
from classlop.grading.scoring import Score, score
from classlop.grading.transcription import ItemTranscription, transcribe
from classlop.grading.verification import verify
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
    assignment_id: uuid.UUID
    due_at: datetime


class Input(TypedDict):
    job: GradeJob


class State(Input):
    items: list[tuple[int, ItemVersion]]
    pages: list[bytes]
    # The Held reason when the files cannot be transcribed at all.
    file_problem: str | None
    transcriptions: dict[int, ItemTranscription]
    # The verification note per disputed Item number.
    disputes: dict[int, str]
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
            assignment_id=job.assignment_id,
            due_at=job.due_at,
            status="graded",
            held_reasons=held,
            spot_check_reasons=held,
            comment="",
            items=[],
        )
    }


async def transcribe_pages(state: State) -> dict:
    return {"transcriptions": await transcribe(state["items"], state["pages"])}


async def verify_pages(state: State) -> dict:
    """A disputed Item becomes unsure, so the Teacher sees it before any Student does."""
    transcriptions = state["transcriptions"]
    checks = await verify(state["items"], state["pages"], transcriptions)
    disputes = {
        n: check.note if check else "brak weryfikacji"
        for n in transcriptions
        if (check := checks.get(n)) is None or check.verdict == "disputed"
    }
    return {
        "disputes": disputes,
        "transcriptions": {
            # A dispute only lowers confidence: unreadable work is never turned into a guess.
            n: t.model_copy(update={"reading": "unsure"})
            if n in disputes and t.reading != "unreadable"
            else t
            for n, t in transcriptions.items()
        },
    }


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
        and t.transcription.strip()
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
    dispute: str | None,
) -> GradedItem:
    reading = _reading(item, transcription)
    if item.item_format == "closed":
        chosen = transcription.chosen_option if transcription else None
        right = reading not in UNSCORED and [chosen] == item.correct_options
        points = item.points if right else 0
        wrong_choice = reading not in UNSCORED and not right and chosen in item.options
        mistake = chosen_option_mistake(chosen) if wrong_choice and chosen else None
    else:
        points = min(max(scored.points, 0), item.points) if scored else 0
        mistake = scored.mistake if scored and points < item.points else None
    if reading == "blank":
        feedback = BLANK
    elif reading == "unreadable" or not (transcription and transcription.transcription.strip()):
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
        mistake=mistake,
        verification_note=dispute,
    )


def text_comment(items: list[GradedItem]) -> str:
    """One points line per Item with its effective points, then the fixed AI line."""
    return "\n".join(_line(i) for i in items) + f"\n\n{AI_LINE}"


def _line(item: GradedItem) -> str:
    points = item.effective_points
    line = f"Zadanie {item.number}: {points}/{item.max_points} pkt"
    if points == item.max_points:
        return f"{line} – {CORRECT}"
    # A wrong remark under the Teacher's points would contradict them; a fixed one never does.
    remark = item.feedback in FIXED_FEEDBACK and item.feedback != CORRECT
    return f"{line} – {item.feedback}" if remark else line


def _reasons(items: list[GradedItem], rules: list[Rule]) -> list[dict]:
    return [
        {"reason": reason, "items": numbers}
        for reason, applies in rules
        if (numbers := [i.number for i in items if applies(i)])
    ]


async def assess(state: State) -> dict:
    job, transcriptions, scores = state["job"], state["transcriptions"], state.get("scores", {})
    graded = [
        _grade_item(
            position, n, item, transcriptions.get(n), scores.get(n), state["disputes"].get(n)
        )
        for position, (n, item) in enumerate(state["items"])
    ]
    held = _reasons(graded, HELD_REASONS)
    return {
        "graded": GradedSubmission(
            submission_id=job.submission_id,
            handed_in_at=job.handed_in_at,
            assignment_id=job.assignment_id,
            due_at=job.due_at,
            status="graded",
            held_reasons=held,
            spot_check_reasons=held + _reasons(graded, FLAG_REASONS),
            comment=text_comment(graded),
            items=graded,
        )
    }


async def persist(state: State) -> dict:
    async with sessions().begin() as session:
        session.add(state["graded"])
    job = state["job"]
    await announce(job.submission_id, job.handed_in_at, first=True)
    await request_if_computed(job.assignment_id)
    return {}


async def announce(submission_id: uuid.UUID, handed_in_at: datetime, first: bool = False) -> None:
    """Tell `teams` the result was written or changed. The first announcement is keyed, so a
    redelivered grading job never tells twice; every later change is its own event."""
    payload = {"submission_id": str(submission_id), "handed_in_at": handed_in_at.isoformat()}
    key = f"teams.submission_graded:{submission_id}@{payload['handed_in_at']}" if first else None
    await jobs.enqueue("teams.submission_graded", payload, key=key)


grade_graph = (
    StateGraph(State, input_schema=Input)
    .add_node(load)
    .add_node(transcribe_pages)
    .add_node(verify_pages)
    .add_node(score_item)
    .add_node(hold)
    .add_sequence([assess, persist])
    .add_edge(START, "load")
    .add_conditional_edges("load", to_transcription, ["transcribe_pages", "hold"])
    .add_edge("transcribe_pages", "verify_pages")
    .add_conditional_edges("verify_pages", to_scoring, ["score_item", "assess"])
    .add_edge("score_item", "assess")
    .add_edge("hold", "persist")
    .compile()
)
