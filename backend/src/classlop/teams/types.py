from datetime import datetime
from typing import Protocol

from pydantic import BaseModel


class NotOwner(Exception):
    """The Teacher does not own that team."""


class AlreadyLinked(Exception):
    """The team is already a Class."""


class Team(BaseModel):
    id: str
    name: str


class Candidate(BaseModel):
    """A tenant user the Teacher may pick as a Student."""

    user_id: str
    display_name: str
    upn: str


class Class(BaseModel):
    id: str
    team_id: str
    general_channel_id: str
    name: str


class Student(BaseModel):
    id: str
    class_id: str
    user_id: str
    display_name: str
    upn: str
    former_since: datetime | None = None


class Teams(Protocol):
    """The `teams` area's interface: the real area and FakeTeams both implement it."""

    async def list_owned_teams(self) -> list[Team]: ...

    async def link_team(self, team_id: str) -> Class:
        """Raises NotOwner or AlreadyLinked; syncs the roster."""
        ...

    async def get_class(self, class_id: str) -> Class: ...

    async def list_classes(self) -> list[Class]: ...

    async def list_students(self, class_id: str) -> list[Student]:
        """Every Student, Former students included (`former_since` set)."""
        ...

    async def sync_roster(self, class_id: str) -> None:
        """Also renames the Class to match its team."""
        ...

    async def search_users(self, query: str) -> list[Candidate]:
        """Tenant users whose name has a word starting with `query`."""
        ...

    async def create_class(self, name: str, student_user_ids: list[str]) -> Class:
        """A new Private team named `name`, the Teacher as owner and the users as members."""
        ...

    async def add_student(self, class_id: str, user_id: str) -> Student: ...

    async def remove_student(self, class_id: str, user_id: str) -> None:
        """Removes them from the team; they become a Former student."""
        ...

    async def rename_class(self, class_id: str, name: str) -> Class:
        """Renames the team too."""
        ...
