"""The home screen: the sidebar and the Do zrobienia queue, in one response."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, get_args
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from classlop import teams
from classlop.dashboard import auth, bank
from classlop.dashboard.classes import TheTeams

router = APIRouter()
WARSAW = ZoneInfo("Europe/Warsaw")

# In the queue's order: the live Lesson, then the problems, then the rest as in #12.
Kind = Literal[
    "live_lesson",
    "sign_in",
    "give_failed",
    "team_removed",
    "calendar_question",
    "graded",
    "next_lesson",
    "deadline",
]
ORDER = get_args(Kind)


class Choice(BaseModel):
    """One answer to a question on the queue: `answer` is what `teams` is told."""

    answer: str
    label: str


class Entry(BaseModel):
    kind: Kind
    title: str
    detail: str
    at: datetime | None = None
    # A question is answered in place, by one of its `choices`, and has no page to open.
    link: str = ""
    action: str = ""
    question_id: str | None = None
    choices: list[Choice] = []


class ClassLink(BaseModel):
    id: str
    name: str
    graded: int


class Home(BaseModel):
    entries: list[Entry]
    entries_invented: bool
    classes: list[ClassLink]
    flagged_items: int
    sidebar_invented: bool


def queue(entries: list[Entry]) -> list[Entry]:
    return sorted(entries, key=lambda e: ORDER.index(e.kind))


def inserted(entries: list[Entry], extra: list[Entry], kind: Kind) -> list[Entry]:
    """`extra`, all of `kind`, where that kind belongs; the rest keeps its order."""
    rank = ORDER.index(kind)
    at = next((i for i, e in enumerate(entries) if ORDER.index(e.kind) > rank), len(entries))
    return [*entries[:at], *extra, *entries[at:]]


def invented(now: datetime) -> Home:
    """Hardcoded stand-in for what `grading` will give (#82): the AI-graded entries and the
    sidebar's invented Classes."""
    entries = [
        Entry(
            kind="graded",
            title="Ocenione przez AI: Równania (2C)",
            detail="Sprawdzian, oddane 7/8",
            link="/klasy/2c/prace/2c-2",
            action="Zobacz",
        ),
        Entry(
            kind="graded",
            title="Ocenione przez AI: Zbiory liczbowe (3B)",
            detail="Praca domowa, oddane 8/8",
            link="/klasy/3b/prace/3b-0",
            action="Zobacz",
        ),
    ]
    return Home(
        entries=entries,
        entries_invented=True,
        classes=[
            ClassLink(id="1a", name="1A", graded=0),
            ClassLink(id="2c", name="2C", graded=1),
            ClassLink(id="3b", name="3B", graded=1),
        ],
        flagged_items=0,
        sidebar_invented=True,
    )


def stand_in() -> Callable[[datetime], Home]:
    """What stands in for the areas until they can give the real thing; the Playwright server
    swaps it for one that reacts to jobs."""
    return invented


async def failed_gives() -> list[Entry]:
    """The Assignments `teams` could not give at their scheduled time, which are Drafts again."""
    entries = []
    for a in await teams.list_failed_gives():
        try:
            name = (await teams.get_class(a.class_id)).name
        except LookupError:
            continue
        entries.append(
            Entry(
                kind="give_failed",
                title=f"Nie udało się wydać pracy «{a.title}»",
                detail=f"Teams odrzucił publikację dla klasy {name}",
                at=a.give_failed_at,
                link=f"/klasy/{a.class_id}/prace/{a.id}",
                action="Otwórz pracę",
            )
        )
    return entries


TYPES = {"homework": "Praca domowa", "quiz": "Kartkówka", "exam": "Sprawdzian"}
HANDED_IN = {"handed_in", "graded", "returned"}


async def from_teams(
    t: TheTeams, lapsed: Annotated[bool, Depends(auth.sign_in_lapsed)]
) -> list[Entry]:
    """The live and the next Lesson, the problems and the deadlines, from one `teams` read per
    Class."""
    now = datetime.now(UTC)
    entries = [
        Entry(
            kind="sign_in",
            title="Zaloguj się ponownie",
            detail="Logowanie do Teams wygasło, część zadań czeka",
            link="/auth/login",
            action="Zaloguj się",
        )
    ] * lapsed
    entries += [
        Entry(
            kind="team_removed",
            title=f"Zespół klasy {c.name} usunięto w Teams",
            detail="Praca i lekcje tej klasy nie zostaną już pobrane",
            link=f"/klasy/{c.id}/ustawienia",
            action="Otwórz ustawienia klasy",
        )
        for c in await t.list_deleted_teams()
    ]
    coming: list[tuple[teams.Lesson, teams.Class]] = []
    for c in await t.list_classes():
        if c.state != "active":
            continue
        read = await t.read_class(c.id)
        for lesson in read.lessons:
            if lesson.cancelled or lesson.end <= now:
                continue
            if lesson.start > now:
                coming.append((lesson, c))
                continue
            entries.append(
                Entry(
                    kind="live_lesson",
                    title=f"Trwa lekcja: klasa {c.name}",
                    detail=lesson.topic or "Bez tematu lekcji",
                    at=lesson.start,
                    link=lesson.join_url,
                    action="Dołącz w Teams",
                )
            )
        for a in read.assignments:
            if a.state != "open" or a.due_at <= now:
                continue
            mine = [s for s in read.submissions if s.assignment_id == a.id]
            handed_in = sum(s.state in HANDED_IN for s in mine)
            entries.append(
                Entry(
                    kind="deadline",
                    title=f"Termin: {a.title} ({c.name})",
                    detail=f"{TYPES[a.type]}, oddane {handed_in}/{len(mine)}",
                    at=a.due_at,
                    link=f"/klasy/{c.id}/prace/{a.id}",
                    action="Otwórz pracę",
                )
            )
    if coming:
        lesson, c = min(coming, key=lambda found: found[0].start)
        entries.append(
            Entry(
                kind="next_lesson",
                title=f"Lekcja: klasa {c.name}",
                detail=lesson.topic or "Bez tematu lekcji",
                at=lesson.start,
                link=f"/klasy/{c.id}/lekcje/{lesson.id}",
                action="Otwórz lekcję",
            )
        )
    return entries


async def calendar_questions(t: TheTeams) -> list[Entry]:
    """The Teams meetings the Teacher is asked to sort: which Class, or keep or hide."""
    names = {c.id: c.name for c in await t.list_classes()}
    entries = []
    for q in await t.list_calendar_questions():
        which = [Choice(answer=c, label=names[c]) for c in q.candidates if c in names]
        entries.append(
            Entry(
                kind="calendar_question",
                title="Do której klasy należy to spotkanie?"
                if which
                else "Co zrobić z tym spotkaniem?",
                detail=f"«{q.subject}», {q.start.astimezone(WARSAW):%d.%m %H:%M}",
                at=q.start,
                question_id=q.id,
                choices=which
                or [
                    Choice(answer="keep", label="Zostaw w kalendarzu"),
                    Choice(answer="hide", label="Ukryj"),
                ],
            )
        )
    return entries


@router.get("/api/home")
async def home(
    _: Annotated[auth.Me, Depends(auth.teacher)],
    items: bank.TheBank,
    t: TheTeams,
    make: Annotated[Callable[[datetime], Home], Depends(stand_in)],
    failed: Annotated[list[Entry], Depends(failed_gives)],
    found: Annotated[list[Entry], Depends(from_teams)],
    asked: Annotated[list[Entry], Depends(calendar_questions)],
) -> Home:
    view = make(datetime.now(UTC))
    # The Teacher's own Classes follow the invented ones in the sidebar, until the rest is wired.
    own = [ClassLink(id=c.id, name=c.name, graded=0) for c in await t.list_classes()]
    return view.model_copy(
        update={
            "entries": inserted(
                inserted(queue([*view.entries, *found]), failed, "give_failed"),
                asked,
                "calendar_question",
            ),
            "classes": [*view.classes, *own],
            "flagged_items": await bank.flagged_count(items),
        }
    )
