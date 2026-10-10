import re
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from ulid import ULID

from classlop.shared.db import sessions
from classlop.shared.settings import get_settings
from classlop.teams.graph import BASE, GraphClient
from classlop.teams.models import ClassRecord, StudentRecord
from classlop.teams.types import AlreadyLinked, Candidate, Class, NotOwner, Student, Team


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
        return await self._link(team_id, team.name)

    async def _link(self, team_id: str, name: str) -> Class:
        channel = await self._graph.get(f"/teams/{team_id}/primaryChannel")
        row = ClassRecord(
            id=str(ULID()), team_id=team_id, general_channel_id=channel["id"], name=name
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
        name = (await self._graph.get(f"/teams/{klass.team_id}"))["displayName"]
        members = await self._graph.get_all(f"/teams/{klass.team_id}/members")
        present = {m["userId"]: m for m in members if "owner" not in m["roles"]}
        async with sessions().begin() as session:
            (await session.get_one(ClassRecord, class_id)).name = name
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

    async def search_users(self, query: str) -> list[Candidate]:
        users = await self._graph.get_all(
            "/users",
            **{"$search": f'"displayName:{query}"', "$select": "id,displayName,userPrincipalName"},
            headers={"ConsistencyLevel": "eventual"},
        )
        return [
            Candidate(user_id=u["id"], display_name=u["displayName"], upn=u["userPrincipalName"])
            for u in users
        ]

    async def create_class(self, name: str, student_user_ids: list[str]) -> Class:
        owner = get_settings().m365_teacher_oid
        response = await self._graph.request(
            "POST",
            "/teams",
            json={
                "template@odata.bind": f"{BASE}/teamsTemplates('standard')",
                "displayName": name,
                "visibility": "Private",
                "members": [_member(owner, "owner"), *(_member(u) for u in student_user_ids)],
            },
        )
        team_id = re.search(r"'([^']+)'", response.headers["Content-Location"])[1]
        operation = re.search(r"operations\('([^']+)'\)", response.headers["Location"])[1]
        await self._graph.wait_for(f"/teams/{team_id}/operations/{operation}")
        return await self._link(team_id, name)

    async def add_student(self, class_id: str, user_id: str) -> Student:
        klass = await self.get_class(class_id)
        await self._graph.request("POST", f"/teams/{klass.team_id}/members", json=_member(user_id))
        await self.sync_roster(class_id)
        return next(s for s in await self.list_students(class_id) if s.user_id == user_id)

    async def remove_student(self, class_id: str, user_id: str) -> None:
        klass = await self.get_class(class_id)
        members = await self._graph.get_all(f"/teams/{klass.team_id}/members")
        for member in members:
            if member["userId"] == user_id:
                await self._graph.request(
                    "DELETE", f"/teams/{klass.team_id}/members/{member['id']}"
                )
        await self.sync_roster(class_id)

    async def rename_class(self, class_id: str, name: str) -> Class:
        klass = await self.get_class(class_id)
        await self._graph.request("PATCH", f"/teams/{klass.team_id}", json={"displayName": name})
        async with sessions().begin() as session:
            row = await session.get_one(ClassRecord, class_id)
            row.name = name
        return klass.model_copy(update={"name": name})


def _member(user_id: str, *roles: str) -> dict:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "roles": list(roles),
        "user@odata.bind": f"{BASE}/users('{user_id}')",
    }
