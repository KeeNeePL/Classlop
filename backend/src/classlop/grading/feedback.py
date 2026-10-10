"""The Student's Feedback: the text comment, which carries no maths, and the typeset PDF."""

import asyncio
import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from classlop.grading.models import GradedItem
from classlop.shared import llm, storage
from classlop.shared.typeset import Heading, Paragraph, TypesetError, render

AI_LINE = "Ocena i komentarz przygotowane przez AI; nauczyciel sprawdza je wyrywkowo."
CORRECT, BLANK = "poprawnie", "brak rozwiązania"
NOT_READ, WRONG = "nie udało się odczytać rozwiązania", "błędna odpowiedź"
# Fixed Feedback carries no maths, so the text comment shows it; scored Feedback may carry maths.
FIXED_FEEDBACK = (CORRECT, BLANK, NOT_READ, WRONG)
MAX_CURRICULUM_TOPICS = 2

PROMPT = """You sum up a student's graded Polish high-school maths test for the student.
You get one line per Item: its number, the points and the Feedback the student also receives.

Write one or two Polish sentences on what went well and what to work on, naming Items by number.
Impersonal, addressing the student as "ty", factual and calm; criticise the work, never the
person; no exclamation marks, no emoji. The student's gender is unknown, so no gendered past
tense ("poradziłeś", "policzyłaś"): say "rozwiązanie zadania 2 jest poprawne", "w zadaniu 4
pojawia się błąd". No filler about keeping up the good work.
Plain text only: no mathematics, no formulas, no LaTeX.
Never give the final answer of any Item, a points total or a school grade. Where work could not be
read, say so and never guess what it said."""


class Summary(BaseModel):
    summary: str


async def summarise(items: list[GradedItem]) -> str:
    graded = "\n".join(f"{_points(i)}. {fitting_feedback(i) or ''}" for i in items)
    reply = await llm.ask("grading.summary", Summary, [SystemMessage(PROMPT), HumanMessage(graded)])
    return reply.summary.strip()


def text_comment(summary: str, items: list[GradedItem]) -> str:
    topics = to_revise(items)
    revise = "Do powtórki:\n" + "\n".join(f"- {t}" for t in topics) if topics else ""
    lines = "\n".join(_line(i) for i in items)
    return "\n\n".join(part for part in (summary, lines, revise, AI_LINE) if part)


def to_revise(items: list[GradedItem]) -> list[str]:
    """The first Curriculum topics of the Items that lost points, in Item order."""
    lost = (t for i in items if i.effective_points < i.max_points for t in i.curriculum_topics)
    return list(dict.fromkeys(lost))[:MAX_CURRICULUM_TOPICS]


def fitting_feedback(item: GradedItem) -> str | None:
    """The Teacher's wording, or the AI Feedback that fits the effective points: the Teacher's
    points may contradict the AI's."""
    if item.edited_feedback is not None:
        return item.edited_feedback
    if item.effective_points == item.max_points:
        return CORRECT
    return None if item.feedback == CORRECT else item.feedback


def _points(item: GradedItem) -> str:
    return f"Zadanie {item.number}: {item.effective_points}/{item.max_points} pkt"


def _line(item: GradedItem) -> str:
    feedback = fitting_feedback(item)
    return f"{_points(item)} – {feedback}" if feedback in FIXED_FEEDBACK else _points(item)


async def store_pdf(submission_id: uuid.UUID, items: list[GradedItem]) -> str:
    """Typeset the Feedback PDF and store it under a new key, so every version has its own."""
    pdf = await asyncio.to_thread(render, document(items))
    key = f"grading/feedback/{submission_id}/{uuid.uuid4()}.pdf"
    await asyncio.to_thread(storage.put, key, pdf, "application/pdf")
    return key


async def typesets(feedback: str) -> bool:
    try:
        await asyncio.to_thread(render, [Paragraph(feedback)])
    except TypesetError:
        return False
    return True


async def feedback_typesets(item: GradedItem) -> bool:
    feedback = fitting_feedback(item)
    return not feedback or feedback in FIXED_FEEDBACK or await typesets(feedback)


def document(items: list[GradedItem]) -> list[Heading | Paragraph]:
    """Per Item its points and Feedback, then the AI line; never a total or the transcription."""
    blocks: list[Heading | Paragraph] = []
    for item in items:
        blocks.append(Heading(_points(item)))
        if feedback := fitting_feedback(item):
            fixed = feedback in FIXED_FEEDBACK
            blocks.append(Paragraph(f"{feedback.capitalize()}." if fixed else feedback))
    return [*blocks, Paragraph(AI_LINE)]
