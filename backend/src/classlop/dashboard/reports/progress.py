"""Progress: points earned over available on graded Items. Missing, Excused and Held Submissions
and Submissions not yet graded are left out; what was never assessed has no percent."""

from collections.abc import Iterable, Sequence

from pydantic import BaseModel

from classlop.dashboard.reports.records import ScoredItem, Submission
from classlop.items import CurriculumSection


class Bar(BaseModel):
    earned: int
    available: int
    # None is "brak danych", never 0%.
    percent: int | None


class TopicBar(Bar):
    id: str
    name: str


class SectionBar(Bar):
    id: str
    name: str
    topics: list[TopicBar]


def bar(earned: int, available: int) -> Bar:
    percent = (200 * earned + available) // (2 * available) if available else None
    return Bar(earned=earned, available=available, percent=percent)


def counted(submissions: Iterable[Submission]) -> list[ScoredItem]:
    return [
        i for s in submissions if s.state in ("graded", "returned") and not s.held for i in s.items
    ]


def overall(items: Iterable[ScoredItem]) -> Bar:
    items = list(items)
    return bar(sum(i.earned for i in items), sum(i.available for i in items))


def progress(
    items: Sequence[ScoredItem], sections: Sequence[CurriculumSection]
) -> list[SectionBar]:
    """An Item counts in full for each of its topics, and once for each section it touches."""
    result = []
    for section in sections:
        ids = {t.id for t in section.topics}
        topics = [
            TopicBar(
                id=t.id,
                name=t.name,
                **overall(i for i in items if t.id in i.topic_ids).model_dump(),
            )
            for t in section.topics
        ]
        own = overall(i for i in items if ids.intersection(i.topic_ids))
        result.append(
            SectionBar(id=section.id, name=section.name, topics=topics, **own.model_dump())
        )
    return result
