"""The dashboard with the Teacher signed in and no database, for the Playwright tests in
frontend/e2e. The Item bank is a few invented Items in memory; one invented job can be finished;
the Classlop AI tab talks to a fake Chat. `teams` for the Classes screens is FakeTeams with its
demo tenant."""

from datetime import UTC, datetime, timedelta

from fake_bank import InMemoryBank
from fake_chats import InMemoryChats
from fake_events import InMemoryFeed
from fake_grading import InMemoryGrader
from fake_store import InMemoryStore
from fake_work import Offline, invented_class
from fastapi import FastAPI

from classlop import teams
from classlop.dashboard import (
    auth,
    bank,
    chats,
    classes,
    events,
    grader,
    home,
    invented,
    new_work,
    store,
)
from classlop.dashboard.app import create_app
from classlop.teams.fake import FakeTeams, demo


def create() -> FastAPI:
    app = create_app()
    app.dependency_overrides[auth.teacher] = lambda: auth.Me(name="Anna Nowak")
    app.dependency_overrides[auth.sign_in_lapsed] = lambda: False
    items = InMemoryBank()
    app.dependency_overrides[bank.backend] = lambda: items
    graded = InMemoryGrader()
    app.dependency_overrides[grader.backend] = lambda: graded
    feed = InMemoryFeed()
    app.dependency_overrides[events.job_feed] = lambda: feed
    talk = InMemoryChats(items, feed)
    app.dependency_overrides[chats.backend] = lambda: talk
    app.dependency_overrides[home.stand_in] = lambda: feed.home
    kept = InMemoryStore()
    app.state.store = kept
    app.dependency_overrides[store.backend] = lambda: kept
    app.dependency_overrides[home.failed_gives] = failed_give
    app.dependency_overrides[home.from_teams] = from_teams
    app.state.teams = demo()
    app.dependency_overrides[classes.backend] = lambda: app.state.teams

    # The Playwright tests share this server, so one that changes the bank or the Classes puts it
    # back.
    @app.post("/api/e2e/reset", include_in_schema=False)
    async def reset() -> None:
        items.reset()
        invented.reset()
        graded.reset()
        feed.reset()
        talk.reset()
        app.state.teams = demo()
        kept.reset()

    @app.post("/api/e2e/attend", include_in_schema=False)
    async def attend(class_id: str) -> None:
        """A call record for each Lesson of the Class: Jan joins on time, Ewa 9 minutes late,
        Piotr never, and a guest called Piotrek W. joins unlinked."""
        fake: FakeTeams = app.state.teams
        users = {s.display_name: s.user_id for s in await fake.list_students(class_id)}
        who = [
            (users["Jan Kowalski"], "Jan Kowalski", 1),
            (users["Ewa Zielinska"], "Ewa Zielinska", 9),
            (None, "Piotrek W.", 2),
        ]
        for lesson in await fake.list_lessons(class_id):
            fake.attend(
                lesson.join_url,
                [(u, n, lesson.start + timedelta(minutes=m), lesson.end) for u, n, m in who],
            )

    @app.post("/api/e2e/meeting", include_in_schema=False)
    async def meeting(class_id: str) -> None:
        """A Teams meeting that the Class's Students and a stranger were invited to."""
        fake: FakeTeams = app.state.teams
        invited = [s.upn for s in await fake.list_students(class_id)]
        start = datetime.now(UTC) + timedelta(days=2)
        fake.add_meeting(
            "Wycieczka do muzeum",
            start,
            start + timedelta(hours=1),
            attendees=[*invited[:1], "gosc@example.org"],
        )

    @app.post("/api/e2e/grade", include_in_schema=False)
    async def grade() -> None:
        feed.grade()

    return app


def failed_give() -> list[home.Entry]:
    return [
        home.Entry(
            kind="give_failed",
            title="Nie udało się wydać pracy «Ciągi: zadania z treścią»",
            detail="Teams odrzucił publikację dla klasy 2C",
            link="/klasy/2c/prace/ciagi",
            action="Otwórz pracę",
        )
    ]


def from_teams() -> list[home.Entry]:
    """What `teams` would give the queue for the invented Classes."""
    now = datetime.now(UTC)
    return [
        home.Entry(
            kind="deadline",
            title="Termin: Wzory skróconego mnożenia (1A)",
            detail="Praca domowa, oddane 17/26",
            at=now + timedelta(hours=9),
            link="/klasy/1a/prace/1a-4",
            action="Otwórz pracę",
        ),
        home.Entry(
            kind="team_removed",
            title="Zespół klasy 3B usunięto w Teams",
            detail="Praca i lekcje tej klasy nie zostaną już pobrane",
            link="/klasy/3b/ustawienia",
            action="Otwórz ustawienia klasy",
        ),
        home.Entry(
            kind="next_lesson",
            title="Lekcja: klasa 3B",
            detail="Graniastosłupy: pola i objętości",
            at=now + timedelta(hours=3),
            link="/klasy/3b/lekcje/graniastoslupy",
            action="Otwórz lekcję",
        ),
        home.Entry(
            kind="sign_in",
            title="Zaloguj się ponownie",
            detail="Logowanie do Teams wygasło, część zadań czeka",
            link="/auth/login",
            action="Zaloguj się",
        ),
        home.Entry(
            kind="live_lesson",
            title="Trwa lekcja: klasa 1A",
            detail="Wzory skróconego mnożenia",
            at=now - timedelta(minutes=20),
            link="https://teams.microsoft.com/l/meetup-join/1a-wzory",
            action="Dołącz w Teams",
        ),
    ]


def serve() -> FastAPI:
    """`create()` for the Playwright server, with giving over FakeTeams: the invented Class 1A of
    the sidebar is a Class of FakeTeams, whose giving asks `items`, the scheduler and the job
    queue nothing a database is needed for."""
    app = create()
    items = app.dependency_overrides[bank.backend]()
    fake = FakeTeams()
    teams._backend = fake
    for module, name, replacement in Offline(items).patches():
        setattr(module, name, replacement)
    linked: list[str] = []

    async def team_class(class_id: str) -> str:
        if class_id != "1a":
            return class_id
        if not linked:
            linked.append((await invented_class(fake)).id)
        return linked[0]

    app.dependency_overrides[new_work.team_class] = team_class

    # A POST: the app's catch-all GET route comes first.
    @app.post("/api/e2e/posts", include_in_schema=False)
    async def posts() -> list[str]:
        """The files posted in General, by name."""
        return [name for team in fake._teams for p in fake.channel_posts(team) for name in p.files]

    return app
