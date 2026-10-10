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

    async def sync_roster(self, class_id: str) -> None: ...
