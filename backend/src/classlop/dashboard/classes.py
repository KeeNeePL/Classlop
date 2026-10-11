"""Creating, linking, managing and deleting a Class: every action goes through `teams`, which keeps
the Class and its team in step. The Notes are the dashboard's own and go with the Class."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StringConstraints

from classlop import teams
from classlop.dashboard import auth, notes
from classlop.dashboard.actions import carry_out, refusing

router = APIRouter()

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def backend() -> teams.Teams:
    return teams.backend()


TheTeams = Annotated[teams.Teams, Depends(backend)]
Teacher = Annotated[auth.Me, Depends(auth.teacher)]


class Created(BaseModel):
    id: str
    name: str


class Member(BaseModel):
    id: str
    user_id: str
    name: str
    upn: str
    # A Former student: shown as "były uczeń".
    former: bool


class ClassSettings(BaseModel):
    id: str
    name: str
    state: teams.ClassState
    team_deleted_at: datetime | None
    students: list[Member]


class NewClass(BaseModel):
    name: Name
    student_user_ids: list[str]


class LinkTeam(BaseModel):
    team_id: str


class Rename(BaseModel):
    name: Name


class NewStudent(BaseModel):
    user_id: str


@router.get("/api/users")
async def users(_: Teacher, t: TheTeams, q: str = "") -> list[teams.Candidate]:
    """Tenant users to pick as Students, by name."""
    with refusing():
        return await t.search_users(q)


@router.get("/api/teams")
async def owned_teams(_: Teacher, t: TheTeams) -> list[teams.Team]:
    """The teams the Teacher owns and has not linked yet."""
    with refusing():
        linked = {c.team_id for c in await t.list_classes()}
        return [team for team in await t.list_owned_teams() if team.id not in linked]


@router.post("/api/classes")
async def create_class(body: NewClass, _: Teacher, t: TheTeams) -> Created:
    with refusing():
        made = await t.create_class(body.name, body.student_user_ids)
    return Created(id=made.id, name=made.name)


@router.post("/api/classes/link")
async def link_team(body: LinkTeam, _: Teacher, t: TheTeams) -> Created:
    with refusing():
        made = await t.link_team(body.team_id)
    return Created(id=made.id, name=made.name)


@router.get("/api/classes/{class_id}/settings")
async def class_settings(class_id: str, _: Teacher, t: TheTeams) -> ClassSettings:
    """The roster is brought in step with the team first, as when the Class page opens."""
    with refusing():
        if (await t.get_class(class_id)).state == "active":
            await t.sync_roster(class_id)
        klass = await t.get_class(class_id)
        students = await t.list_students(class_id)
    return ClassSettings(
        id=klass.id,
        name=klass.name,
        state=klass.state,
        team_deleted_at=klass.team_deleted_at,
        students=[
            Member(
                id=s.id,
                user_id=s.user_id,
                name=s.display_name,
                upn=s.upn,
                former=s.former_since is not None,
            )
            for s in students
        ],
    )


@router.patch("/api/classes/{class_id}", status_code=204)
async def rename_class(class_id: str, body: Rename, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(t.rename_class(class_id, body.name))


@router.post("/api/classes/{class_id}/students", status_code=204)
async def add_student(class_id: str, body: NewStudent, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(t.add_student(class_id, body.user_id))


@router.delete("/api/classes/{class_id}/students/{student_id}", status_code=204)
async def remove_student(class_id: str, student_id: str, _: Teacher, t: TheTeams) -> Response:
    with refusing():
        student = next((s for s in await t.list_students(class_id) if s.id == student_id), None)
    if student is None:
        raise HTTPException(404)
    return await carry_out(t.remove_student(class_id, student.user_id))


@router.post("/api/classes/{class_id}/restore-team", status_code=204)
async def restore_team(class_id: str, _: Teacher, t: TheTeams) -> Response:
    return await carry_out(t.restore_team(class_id))


@router.delete("/api/classes/{class_id}", status_code=204)
async def delete_class(
    class_id: str,
    name: str,
    _: Teacher,
    t: TheTeams,
    kept: Annotated[notes.Notes, Depends(notes.backend)],
) -> Response:
    """Deletes the Class and its team once its name is typed, then its Notes. The Notes go last, so
    a refused deletion loses nothing."""
    with refusing():
        await t.delete_class(class_id, name)
        await kept.delete_class(class_id)
    return Response(status_code=204)
