"""The home screen: the sidebar and the Do zrobienia queue, in one response."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal, get_args

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from classlop.dashboard import auth

router = APIRouter()

# In the queue's order: the live Lesson, then the problems, then the rest as in #12.
Kind = Literal[
    "live_lesson",
    "sign_in",
    "give_failed",
    "team_removed",
    "graded",
    "next_lesson",
    "deadline",
]
ORDER = get_args(Kind)


class Entry(BaseModel):
    kind: Kind
    title: str
    detail: str
    at: datetime | None = None
    link: str
    action: str


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


def invented(now: datetime) -> Home:
    """Hardcoded stand-in until the areas can give the real thing; every part is flagged."""
    entries = [
        Entry(
            kind="deadline",
            title="Termin: Wzory skróconego mnożenia (1A)",
            detail="Praca domowa · oddane 17/26",
            at=now + timedelta(hours=9),
            link="/klasy/1a/prace/wzory",
            action="Otwórz pracę",
        ),
        Entry(
            kind="graded",
            title="Ocenione przez AI: Funkcja kwadratowa (2C)",
            detail="Sprawdzian · średnio 64% · oddane 24/24",
            link="/klasy/2c/prace/funkcja-kwadratowa",
            action="Zobacz",
        ),
        Entry(
            kind="team_removed",
            title="Zespół klasy 3B usunięto w Teams",
            detail="Praca i lekcje tej klasy nie zostaną już pobrane",
            link="/klasy/3b/ustawienia",
            action="Otwórz ustawienia klasy",
        ),
        Entry(
            kind="next_lesson",
            title="Lekcja: klasa 3B",
            detail="Graniastosłupy: pola i objętości",
            at=now + timedelta(hours=3),
            link="/klasy/3b/lekcje/graniastoslupy",
            action="Otwórz lekcję",
        ),
        Entry(
            kind="graded",
            title="Ocenione przez AI: Graniastosłupy (3B)",
            detail="Praca domowa · średnio 71% · oddane 20/22 · 2 do sprawdzenia",
            link="/klasy/3b/prace/graniastoslupy",
            action="Zobacz",
        ),
        Entry(
            kind="give_failed",
            title="Nie udało się wydać pracy «Ciągi: zadania z treścią»",
            detail="Teams odrzucił publikację dla klasy 2C",
            link="/klasy/2c/prace/ciagi",
            action="Otwórz pracę",
        ),
        Entry(
            kind="sign_in",
            title="Zaloguj się ponownie",
            detail="Logowanie do Teams wygasło, część zadań czeka",
            link="/auth/login",
            action="Zaloguj się",
        ),
        Entry(
            kind="live_lesson",
            title="Trwa lekcja: klasa 1A",
            detail="Wzory skróconego mnożenia",
            at=now - timedelta(minutes=20),
            link="/klasy/1a/lekcje/wzory",
            action="Otwórz lekcję",
        ),
    ]
    return Home(
        entries=queue(entries),
        entries_invented=True,
        classes=[
            ClassLink(id="1a", name="1A", graded=0),
            ClassLink(id="2c", name="2C", graded=1),
            ClassLink(id="3b", name="3B", graded=1),
        ],
        flagged_items=4,
        sidebar_invented=True,
    )


@router.get("/api/home")
async def home(_: Annotated[auth.Me, Depends(auth.teacher)]) -> Home:
    return invented(datetime.now(UTC))
