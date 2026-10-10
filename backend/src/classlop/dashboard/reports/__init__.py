"""The Reports core: pure functions over records, no I/O. Endpoints fetch and call it."""

from classlop.dashboard.reports.overview import ClassOverview, class_overview
from classlop.dashboard.reports.records import (
    Assignment,
    ClassData,
    Lesson,
    ScoredItem,
    Student,
    Submission,
)

__all__ = [
    "Assignment",
    "ClassData",
    "ClassOverview",
    "Lesson",
    "ScoredItem",
    "Student",
    "Submission",
    "class_overview",
]
