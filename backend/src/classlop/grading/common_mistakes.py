import uuid
from datetime import UTC, datetime

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, computed_field
from sqlalchemy import and_, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from classlop import items as items_area
from classlop.grading.models import (
    CommonMistake,
    CommonMistakesRun,
    GradedItem,
    GradedSubmission,
    Override,
)
from classlop.shared import jobs, llm
from classlop.shared.db import sessions

# A burst of the Teacher's edits makes one recompute, not one per edit.
DELAY = 120
MIN_SUBMISSIONS = 3
MAX_PER_ITEM = 3

PROMPT = """You group the mistakes students made on one Item of a Polish high-school maths test.
You get the Item text and a numbered list of short Polish mistake descriptions, one per student.

Return clusters of entries that name the same mistake, even when worded differently:
- description: the mistake in a few Polish words, as a teacher would name it to re-teach it;
- members: the numbers of the entries in the cluster.

Each entry belongs to at most one cluster. Do not merge different mistakes into one cluster."""


class Cluster(BaseModel):
    description: str
    members: list[int]


class Clusters(BaseModel):
    clusters: list[Cluster]


class Mistake(BaseModel):
    description: str
    submission_ids: list[uuid.UUID]

    @computed_field
    @property
    def count(self) -> int:
        return len(self.submission_ids)


class ItemMistakes(BaseModel):
    item_id: uuid.UUID
    number: int
    mistakes: list[Mistake]


async def common_mistakes(assignment_id: uuid.UUID) -> list[ItemMistakes]:
    """Per Item of the Assignment, at most three Common mistakes, most frequent first."""
    async with sessions()() as session:
        rows = await session.scalars(
            select(CommonMistake)
            .where(CommonMistake.assignment_id == assignment_id)
            .order_by(CommonMistake.number, CommonMistake.rank)
        )
        found: dict[uuid.UUID, ItemMistakes] = {}
        for row in rows:
            entry = found.setdefault(
                row.item_id, ItemMistakes(item_id=row.item_id, number=row.number, mistakes=[])
            )
            entry.mistakes.append(
                Mistake(description=row.description, submission_ids=row.submission_ids)
            )
    return list(found.values())


async def request_common_mistakes(assignment_id: uuid.UUID) -> None:
    """Record a recompute request and run it after DELAY unless a newer one arrives."""
    now = datetime.now(UTC)
    async with sessions().begin() as session:
        await session.execute(
            insert(CommonMistakesRun)
            .values(assignment_id=assignment_id, requested_at=now)
            .on_conflict_do_update(index_elements=["assignment_id"], set_={"requested_at": now})
        )
    payload = {"assignment_id": str(assignment_id), "requested_at": now.isoformat()}
    await jobs.enqueue("grading.common_mistakes", payload, delay=DELAY)


async def request_if_computed(assignment_id: uuid.UUID) -> None:
    """After the first run, every newly graded Submission (a Late one, or one graded after the
    due-time run) asks for a recompute."""
    async with sessions()() as session:
        computed = await session.scalar(
            select(CommonMistakesRun.computed_at).where(
                CommonMistakesRun.assignment_id == assignment_id
            )
        )
    if computed is not None:
        await request_common_mistakes(assignment_id)


async def superseded(assignment_id: uuid.UUID, requested_at: datetime) -> bool:
    async with sessions()() as session:
        latest = await session.scalar(
            select(CommonMistakesRun.requested_at).where(
                CommonMistakesRun.assignment_id == assignment_id
            )
        )
    return latest is not None and latest > requested_at


async def recompute(assignment_id: uuid.UUID) -> None:
    latest = (
        select(GradedSubmission.submission_id, func.max(GradedSubmission.handed_in_at).label("at"))
        .where(GradedSubmission.assignment_id == assignment_id)
        .group_by(GradedSubmission.submission_id)
        .subquery()
    )
    async with sessions()() as session:
        rows = await session.execute(
            select(
                GradedItem.item_id,
                GradedItem.number,
                GradedItem.submission_id,
                GradedItem.mistake,
                GradedItem.max_points,
                Override.points,
            )
            .join(
                latest,
                and_(
                    GradedItem.submission_id == latest.c.submission_id,
                    GradedItem.handed_in_at == latest.c.at,
                ),
            )
            .outerjoin(Override, GradedItem.override_record)
        )
    numbers: dict[uuid.UUID, int] = {}
    made: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = {}
    for item_id, number, submission_id, mistake, max_points, overridden in rows:
        # The Teacher's full points say there was no mistake after all.
        if not mistake or overridden == max_points:
            continue
        numbers[item_id] = number
        made.setdefault(item_id, []).append((submission_id, mistake))

    kept = []
    for item_id, mistakes in made.items():
        if len(mistakes) < MIN_SUBMISSIONS:
            continue
        for rank, mistake in enumerate(await _cluster(item_id, mistakes)):
            kept.append(
                CommonMistake(
                    assignment_id=assignment_id,
                    item_id=item_id,
                    rank=rank,
                    number=numbers[item_id],
                    description=mistake.description,
                    submission_ids=[str(s) for s in mistake.submission_ids],
                )
            )
    async with sessions().begin() as session:
        # Serialises overlapping runs for one Assignment, so their rewrites never collide.
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtext(str(assignment_id)))))
        now = datetime.now(UTC)
        await session.execute(
            insert(CommonMistakesRun)
            .values(assignment_id=assignment_id, computed_at=now)
            .on_conflict_do_update(index_elements=["assignment_id"], set_={"computed_at": now})
        )
        await session.execute(
            delete(CommonMistake).where(CommonMistake.assignment_id == assignment_id)
        )
        session.add_all(kept)


def chosen_option_mistake(label: str) -> str:
    """A closed Item's mistake: the wrong option the Student chose."""
    return f"zaznaczona odpowiedź {label}"


async def _cluster(item_id: uuid.UUID, made: list[tuple[uuid.UUID, str]]) -> list[Mistake]:
    """At most MAX_PER_ITEM clusters of MIN_SUBMISSIONS or more, most frequent first."""
    (item,) = await items_area.get_versions([item_id])
    if item.item_format == "closed":
        # A wrong option is already exact, so it is grouped in code, without a call.
        clusters = [
            Mistake(
                description=f"Uczniowie często zaznaczają odpowiedź {label}",
                submission_ids=[s for s, m in made if m == chosen_option_mistake(label)],
            )
            for label in item.options
        ]
        return _top([c for c in clusters if c.count >= MIN_SUBMISSIONS])
    listed = "\n".join(f"{n}. {' '.join(m.split())}" for n, (_, m) in enumerate(made, 1))
    reply = await llm.ask(
        "grading.common_mistakes",
        Clusters,
        [SystemMessage(PROMPT), HumanMessage(f"Item:\n{item.text}\n\nMistakes:\n{listed}")],
    )
    seen: set[int] = set()
    clusters = []
    for cluster in reply.clusters:
        # A Submission counts once, and numbers the model made up count not at all.
        members = [
            n for n in dict.fromkeys(cluster.members) if 1 <= n <= len(made) and n not in seen
        ]
        seen.update(members)
        if len(members) >= MIN_SUBMISSIONS:
            submissions = [made[n - 1][0] for n in members]
            clusters.append(Mistake(description=cluster.description, submission_ids=submissions))
    return _top(clusters)


def _top(clusters: list[Mistake]) -> list[Mistake]:
    return sorted(clusters, key=lambda c: c.count, reverse=True)[:MAX_PER_ITEM]
