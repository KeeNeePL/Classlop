import asyncio
import operator
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, TypedDict

from langgraph.graph import START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from classlop import items as items_area
from classlop.grading.common_mistakes import chosen_option_mistake, request_if_computed
from classlop.grading.feedback import (
    BLANK,
    CORRECT,
    NOT_READ,
    WRONG,
    store_pdf,
    summarise,
    text_comment,
    typesets,
)
from classlop.grading.models import GradedItem, GradedSubmission, Reading
from classlop.grading.pages import pages_of, prepare
from classlop.grading.scoring import Score, score
from classlop.grading.transcription import ItemTranscription, transcribe
from classlop.grading.verification import verify
from classlop.items import ItemVersion
from classlop.shared import jobs, storage
from classlop.shared.db import sessions
from classlop.shared.typeset import TypesetError

# Nothing to judge, or nothing that may be judged: such Items score 0 with no scoring call.
UNSCORED = ("blank", "unreadable")

Rule = tuple[str, Callable[[GradedItem], bool]]
HELD_REASONS: list[Rule] = [
    ("nieczytelne", lambda i: i.reading == "unreadable"),
    ("niepewny odczyt", lambda i: i.reading == "unsure"),
    ("wątpliwa ocena", lambda i: i.doubt),
]
FLAG_REASONS: list[Rule] = [("rysunek", lambda i: i.drawing)]
TYPESET_FAILED = "błąd składu"
GRADING_FAILED = "ocena nie powiodła się"


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
    # Items whose Feedback would not typeset even when asked for twice.
    untypeset: Annotated[list[int], operator.add]
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
    """The Feedback is typeset here, so a typesetting error shows at grading, not at return."""
    number, item = state["number"], state["item"]
    for _ in range(2):
        scored = await score(item, state["transcription"])
        # Full points show "poprawnie", whatever the Feedback says.
        if scored.points >= item.points or await typesets(scored.feedback):
            return {"scores": {number: scored}}
    return {"scores": {number: scored}, "untypeset": [number]}


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
        curriculum_topics=[t.name for t in item.curriculum_topics],
    )


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
    return {
        "graded": GradedSubmission(
            submission_id=job.submission_id,
            handed_in_at=job.handed_in_at,
            assignment_id=job.assignment_id,
            due_at=job.due_at,
            status="graded",
            items=graded,
        )
    }


async def write_feedback(state: State) -> dict:
    graded = state["graded"]
    graded.summary = await summarise(graded.items)
    await rebuild_feedback(graded, state.get("untypeset", []))
    return {"graded": graded}


async def rebuild_feedback(submission: GradedSubmission, untypeset: list[int]) -> None:
    """Held and Spot-check reasons, the text comment and the PDF, from the Items as they stand;
    no PDF while any Item's Feedback will not typeset."""
    items = submission.items
    held = _reasons(items, HELD_REASONS)
    if untypeset:
        held.append({"reason": TYPESET_FAILED, "items": sorted(untypeset)})
    submission.comment = text_comment(submission.summary, items)
    submission.pdf_key = None
    if not untypeset:
        try:
            submission.pdf_key = await store_pdf(submission.submission_id, items)
        except TypesetError:
            # Each Feedback typeset alone, so no single Item is to blame.
            held.append({"reason": TYPESET_FAILED, "items": []})
    submission.held_reasons = held
    submission.spot_check_reasons = held + _reasons(items, FLAG_REASONS)


async def grade_fixed_item(item: GradedItem, transcription: str) -> None:
    """Grade one Item again from the Teacher's fixed Transcription; the AI's stays beside it."""
    (version,) = await items_area.get_versions([item.item_id])
    closed, written = version.item_format == "closed", bool(transcription.strip())
    fixed = ItemTranscription(
        number=item.number,
        transcription=transcription,
        reading="readable" if written else "blank",
        drawing=item.drawing,
        # The Teacher may write "b", "B." or "(B)" for the label.
        chosen_option=re.sub(r"[^A-Za-z]", "", transcription).upper() if closed else None,
    )
    scored = None
    if not closed and written:
        task = ScoreTask(number=item.number, item=version, transcription=transcription)
        scored = (await score_item(task))["scores"][item.number]
    graded = _grade_item(item.position, item.number, version, fixed, scored, None)
    for field in ("ai_points", "reading", "doubt", "feedback", "mistake", "verification_note"):
        setattr(item, field, getattr(graded, field))
    item.fixed_transcription = transcription


async def persist(state: State) -> dict:
    job, graded = state["job"], state["graded"]
    graded.grade_job = job.model_dump(mode="json")
    async with sessions().begin() as session:
        # Oceń ponownie: a successful run replaces the failed result.
        await session.execute(
            delete(GradedSubmission).where(
                GradedSubmission.submission_id == job.submission_id,
                GradedSubmission.handed_in_at == job.handed_in_at,
                GradedSubmission.status == "failed",
            )
        )
        session.add(graded)
    await announce(job.submission_id, job.handed_in_at, status="graded")
    await request_if_computed(job.assignment_id)
    return {}


async def store_failure(job: GradeJob) -> None:
    """The last attempt failed: the Teacher sees the Submission Held and can grade it again."""
    held = [{"reason": GRADING_FAILED, "items": []}]
    async with sessions().begin() as session:
        # A result written before the failure stands, and is announced below if it was not yet.
        await session.execute(
            insert(GradedSubmission)
            .values(
                submission_id=job.submission_id,
                handed_in_at=job.handed_in_at,
                assignment_id=job.assignment_id,
                due_at=job.due_at,
                status="failed",
                held_reasons=held,
                spot_check_reasons=held,
                comment="",
                grade_job=job.model_dump(mode="json"),
            )
            .on_conflict_do_nothing()
        )
        status = await session.scalar(
            select(GradedSubmission.status).where(
                GradedSubmission.submission_id == job.submission_id,
                GradedSubmission.handed_in_at == job.handed_in_at,
            )
        )
    await announce(job.submission_id, job.handed_in_at, status=status)
    # The newest hand-in now has no Items, so its earlier mistakes no longer count.
    await request_if_computed(job.assignment_id)


async def announce(
    submission_id: uuid.UUID, handed_in_at: datetime, status: str | None = None
) -> None:
    """Tell `teams` the result was written or changed. Grading passes the status it wrote, which
    keys the event, so a redelivered grading job never tells twice while a graded result
    replacing a failed one is told; the Teacher's changes pass none and are each their own."""
    at = handed_in_at.isoformat()
    key = f"teams.submission_graded:{submission_id}@{at}:{status}" if status else None
    payload = {"submission_id": str(submission_id), "handed_in_at": at}
    await jobs.enqueue("teams.submission_graded", payload, key=key)


grade_graph = (
    StateGraph(State, input_schema=Input)
    .add_node(load)
    .add_node(transcribe_pages)
    .add_node(verify_pages)
    .add_node(score_item)
    .add_node(hold)
    .add_sequence([assess, write_feedback, persist])
    .add_edge(START, "load")
    .add_conditional_edges("load", to_transcription, ["transcribe_pages", "hold"])
    .add_edge("transcribe_pages", "verify_pages")
    .add_conditional_edges("verify_pages", to_scoring, ["score_item", "assess"])
    .add_edge("score_item", "assess")
    .add_edge("hold", "persist")
    .compile()
)
