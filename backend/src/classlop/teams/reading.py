"""The one read of a Class that Reports and Do zrobienia make. GraphTeams and FakeTeams both
inherit it, so it is made of the reads they share."""

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from classlop.teams.types import (
    Assignment,
    Attendance,
    Class,
    ClassRead,
    Lesson,
    Student,
    Submission,
)


class Reading:
    _clock: Callable[[], datetime]

    if TYPE_CHECKING:

        async def get_class(self, class_id: str) -> Class: ...
        async def list_students(self, class_id: str) -> list[Student]: ...
        async def list_assignments(self, class_id: str) -> list[Assignment]: ...
        async def list_submissions(self, assignment_id: str) -> list[Submission]: ...
        async def list_lessons(self, class_id: str) -> list[Lesson]: ...
        async def get_attendance(self, class_id: str, lesson_id: str) -> Attendance: ...

    async def read_class(self, class_id: str) -> ClassRead:
        assignments = await self.list_assignments(class_id)
        lessons = await self.list_lessons(class_id)
        now = self._clock()
        return ClassRead(
            klass=await self.get_class(class_id),
            students=await self.list_students(class_id),
            assignments=assignments,
            submissions=[s for a in assignments for s in await self.list_submissions(a.id)],
            lessons=lessons,
            attendance={
                x.id: await self.get_attendance(class_id, x.id)
                for x in lessons
                if x.start <= now and not x.cancelled
            },
        )
