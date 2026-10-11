"""One Class's data for the Reports: an invented Class's from `invented`, a Class of the Teacher's
own from one `teams` read, with its Items' versions from the bank in one call. Nothing of an own
Class is graded until the Reports read `grading` (#82)."""

from collections import defaultdict
from datetime import UTC, datetime

from classlop import teams
from classlop.dashboard import invented
from classlop.dashboard.actions import refusing
from classlop.dashboard.bank import Bank
from classlop.dashboard.reports import (
    Assignment,
    AssignmentItem,
    ClassData,
    Lesson,
    Student,
    Submission,
)

Read = invented.Read


async def read(class_id: str, t: teams.Teams, pool: Bank) -> tuple[Read, bool]:
    """The Class's data and whether it is invented; an unknown Class is a 404."""
    if (found := await invented.read(class_id, datetime.now(UTC), pool)) is not None:
        return found, True
    with refusing():
        return await _own(await t.read_class(class_id), pool), False


async def _own(got: teams.ClassRead, pool: Bank) -> Read:
    given = [a for a in got.assignments if a.state != "draft"]
    pinned = [v for a in given for v in a.item_versions]
    each = iter(await pool.versions(pinned) if pinned else [])
    versions = {a.id: [next(each) for _ in a.item_versions] for a in given}
    submissions = defaultdict(list)
    for s in got.submissions:
        submissions[s.assignment_id].append(
            Submission(student_id=s.student_id, state=s.state, late=s.late)
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
    return Read(data, versions)
