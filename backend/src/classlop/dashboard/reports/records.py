"""What the Reports core reads: immutable records, shaped like the bulk reads of `teams`, `grading`
and `items`, one Class at a time."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class Record(BaseModel):
    model_config = ConfigDict(frozen=True)


class Student(Record):
    id: str
    name: str
    former: bool = False


class ScoredItem(Record):
    """One Item of one Submission: the points after Overrides, over the points it is worth.
    `number` is the Item's place in the Assignment, from 1."""

    number: int
    topic_ids: tuple[str, ...]
    earned: int
    available: int


SubmissionState = Literal["not_handed_in", "handed_in", "graded", "returned", "missing", "excused"]


class Submission(Record):
    student_id: str
    state: SubmissionState
    late: bool = False
    held: bool = False
    # Flagged for the Teacher's Spot-check (every Held Submission is too).
    spot_check: bool = False
    items: tuple[ScoredItem, ...] = ()


class AssignmentItem(Record):
    number: int
    points: int


AssignmentType = Literal["homework", "quiz", "exam"]
AssignmentState = Literal["draft", "scheduled", "open", "closed"]


class Assignment(Record):
    id: str
    title: str
    type: AssignmentType
    # When Teams accepted the publication, or the time it will.
    given_at: datetime
    due: datetime
    close: datetime
    state: AssignmentState
    items: tuple[AssignmentItem, ...]
    submissions: tuple[Submission, ...]


class Lesson(Record):
    """A Lesson that took place; `absent` holds the ids of the Students marked Absent."""

    id: str
    start: datetime
    absent: frozenset[str] = frozenset()


class ClassData(Record):
    id: str
    name: str
    students: tuple[Student, ...]
    assignments: tuple[Assignment, ...]
    lessons: tuple[Lesson, ...] = ()


class Mistake(Record):
    """A Common mistake on one Item, as `grading` found it."""

    number: int
    description: str
    count: int
