"""One Class's data for the Reports: an invented Class's from `invented`, a Class of the Teacher's
own from one `teams` read. Either way the Items' versions come from the bank in one call and the
results from `grading` in one call."""

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from classlop import grading, teams
from classlop.dashboard import invented
from classlop.dashboard.actions import refusing
from classlop.dashboard.bank import Bank
from classlop.dashboard.grader import Grader
from classlop.dashboard.reports import (
    Assignment,
    AssignmentItem,
    ClassData,
    Lesson,
    Student,
    Submission,
)
from classlop.teams.ids import as_uuid

Read = invented.Read


def assignment_uuid(assignment_id: str, invented_class: bool) -> uuid.UUID:
    """The id `grading` knows the Assignment by."""
    if invented_class:
        return invented.assignment_uuid(assignment_id)
    return as_uuid(assignment_id)


async def read(class_id: str, t: teams.Teams, pool: Bank, graded: Grader) -> tuple[Read, bool]:
    """The Class's data and whether it is invented; an unknown Class is a 404."""
    if (found := await invented.read(class_id, datetime.now(UTC), pool, graded)) is not None:
        return found, True
    with refusing():
        return await _own(await t.read_class(class_id), pool, graded), False


async def _own(got: teams.ClassRead, pool: Bank, graded: Grader) -> Read:
    given = [a for a in got.assignments if a.state != "draft"]
    pinned = [v for a in given for v in a.item_versions]
    each = iter(await pool.versions(pinned) if pinned else [])
    versions = {a.id: [next(each) for _ in a.item_versions] for a in given}
    found = await graded.results([as_uuid(a.id) for a in given]) if given else []
    results = {r.submission_id: r for r in found}
    # A newer hand-in still being graded has no result yet: its older one does not count.
    current: dict[tuple[str, str], grading.Result] = {
        (s.assignment_id, s.student_id): r
        for s in got.submissions
        if (r := results.get(as_uuid(s.id))) and r.handed_in_at == s.handed_in_at
    }
    submissions = defaultdict(list)
    for s in got.submissions:
        if s.assignment_id not in versions:
            continue
        submissions[s.assignment_id].append(
            invented.with_result(
                Submission(student_id=s.student_id, state=s.state, late=s.late),
                current.get((s.assignment_id, s.student_id)),
                versions[s.assignment_id],
            )
        )
    data = ClassData(
        id=got.klass.id,
        name=got.klass.name,
        students=tuple(
            Student(id=s.id, name=s.display_name, former=s.former_since is not None)
            for s in got.students
        ),
        assignments=tuple(
            Assignment(
                id=a.id,
                title=a.title,
                type=a.type,
                # A Scheduled Assignment is Given at the time it will be posted.
                given_at=(a.publish_at if a.state == "scheduled" else a.given_at) or a.due_at,
                due=a.due_at,
                close=a.close_at,
                state=a.state,
                items=tuple(
                    AssignmentItem(number=n, points=v.points)
                    for n, v in enumerate(versions[a.id], 1)
                ),
                submissions=tuple(submissions[a.id]),
            )
            for a in given
        ),
        lessons=tuple(
            Lesson(
                id=lesson_id,
                start=next(x.start for x in got.lessons if x.id == lesson_id),
                absent=frozenset(e.student_id for e in a.entries if e.state == "absent"),
            )
            for lesson_id, a in got.attendance.items()
        ),
    )
    files = {(s.assignment_id, s.student_id): s.files for s in got.submissions if s.files}
    return Read(data, versions, current, files)
