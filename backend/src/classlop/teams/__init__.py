"""The `teams` area: Classlop's only link to Teams. Other areas call the functions below; they
are served by the real area over Graph, or by FakeTeams when TEAMS_BACKEND=fake. `dashboard`
passes GRAPH_SCOPES to sign-in, so the Teacher consents to what `teams` uses."""

from classlop.shared.settings import get_settings
from classlop.teams.graph import GRAPH_SCOPES, GraphClient
from classlop.teams.types import AlreadyLinked, Candidate, Class, NotOwner, Student, Team, Teams

__all__ = [
    "GRAPH_SCOPES",
    "AlreadyLinked",
    "Candidate",
    "Class",
    "NotOwner",
    "Student",
    "Team",
    "Teams",
    "add_student",
    "backend",
    "create_class",
    "get_class",
    "link_team",
    "list_classes",
    "list_owned_teams",
    "list_students",
    "remove_student",
    "rename_class",
    "search_users",
    "sync_roster",
]

_backend: Teams | None = None


def backend() -> Teams:
    global _backend
    if _backend is None:
        if get_settings().teams_backend == "fake":
            from classlop.teams.fake import demo

            _backend = demo()
        else:
            from classlop.teams.service import GraphTeams

            _backend = GraphTeams(GraphClient())
    return _backend


async def list_owned_teams() -> list[Team]:
    """The teams the Teacher owns."""
    return await backend().list_owned_teams()


async def link_team(team_id: str) -> Class:
    """Link a team as a Class and make its members who aren't owners Students."""
    return await backend().link_team(team_id)


async def get_class(class_id: str) -> Class:
    return await backend().get_class(class_id)


async def list_classes() -> list[Class]:
    return await backend().list_classes()


async def list_students(class_id: str) -> list[Student]:
    """Students and Former students (`former_since` set)."""
    return await backend().list_students(class_id)


async def sync_roster(class_id: str) -> None:
    """Bring the Class's Students in step with its team now."""
    await backend().sync_roster(class_id)


async def search_users(query: str) -> list[Candidate]:
    """Tenant users to pick as Students, by name."""
    return await backend().search_users(query)


async def create_class(name: str, student_user_ids: list[str]) -> Class:
    """Create a Private team (the Teacher as owner, the users as members) and link it."""
    return await backend().create_class(name, student_user_ids)


async def add_student(class_id: str, user_id: str) -> Student:
    return await backend().add_student(class_id, user_id)


async def remove_student(class_id: str, user_id: str) -> None:
    """Removes them from the team; they become a Former student."""
    await backend().remove_student(class_id, user_id)


async def rename_class(class_id: str, name: str) -> Class:
    """Renames the Class and its team."""
    return await backend().rename_class(class_id, name)
