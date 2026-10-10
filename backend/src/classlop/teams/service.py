from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from classlop.shared.db import sessions
from classlop.teams.graph import GraphClient
from classlop.teams.models import ClassRecord, StudentRecord
from classlop.teams.types import AlreadyLinked, Class, NotOwner, Student, Team


def now() -> datetime:
    return datetime.now(UTC)


def _class(row: ClassRecord) -> Class:
    return Class.model_validate(row, from_attributes=True)


class GraphTeams:
    """The real area: Postgres records kept in step with the team through Graph."""

    def __init__(self, graph: GraphClient, clock: Callable[[], datetime] = now):
        self._graph, self._clock = graph, clock

    async def list_owned_teams(self) -> list[Team]:
        groups = await self._graph.get_all("/me/ownedObjects/microsoft.graph.group")
        return [
            Team(id=g["id"], name=g["displayName"])
            for g in groups
            if "Team" in g.get("resourceProvisioningOptions", [])
        ]

    async def link_team(self, team_id: str) -> Class:
        team = next((t for t in await self.list_owned_teams() if t.id == team_id), None)
        if team is None:
            raise NotOwner(team_id)
        channel = await self._graph.get(f"/teams/{team_id}/primaryChannel")
        row = ClassRecord(
            id=str(ULID()),
            team_id=team_id,
            general_channel_id=channel["id"],
            name=team.name,
        )
        try:
            async with sessions().begin() as session:
                session.add(row)
        except IntegrityError:
            raise AlreadyLinked(team_id) from None
        await self.sync_roster(row.id)
        return _class(row)

    async def get_class(self, class_id: str) -> Class:
        async with sessions()() as session:
            return _class(await session.get_one(ClassRecord, class_id))

    async def list_classes(self) -> list[Class]:
        async with sessions()() as session:
            rows = await session.scalars(select(ClassRecord).order_by(ClassRecord.name))
            return [_class(r) for r in rows]

    async def list_students(self, class_id: str) -> list[Student]:
        async with sessions()() as session:
            rows = await session.scalars(
                select(StudentRecord)
                .where(StudentRecord.class_id == class_id)
                .order_by(StudentRecord.display_name)
            )
            return [Student.model_validate(r, from_attributes=True) for r in rows]

    async def sync_roster(self, class_id: str) -> None:
        """Members who are not owners are Students; anyone else becomes a Former student."""
        klass = await self.get_class(class_id)
        members = await self._graph.get_all(f"/teams/{klass.team_id}/members")
        present = {m["userId"]: m for m in members if "owner" not in m["roles"]}
        async with sessions().begin() as session:
            known = {
                r.user_id: r
                for r in await session.scalars(
                    select(StudentRecord).where(StudentRecord.class_id == class_id)
                )
            }
            for user_id, member in present.items():
                row = known.get(user_id)
                if row is None:
                    row = StudentRecord(id=str(ULID()), class_id=class_id, user_id=user_id)
                    session.add(row)
                row.display_name = member["displayName"]
                row.upn = member.get("email") or ""
                row.former_since = None
            for user_id, row in known.items():
                if user_id not in present and row.former_since is None:
                    row.former_since = self._clock()
