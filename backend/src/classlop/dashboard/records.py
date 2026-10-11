"""The dashboard's own records: the Teacher's Notes and the Suggested grade thresholds. The
screens reach them through `backend()`, which the Playwright app swaps for one in memory."""

from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from classlop.dashboard.models import NoteRow, ThresholdsRow
from classlop.dashboard.reports.grades import THRESHOLDS
from classlop.shared.db import sessions


class Records(Protocol):
    async def note(self, class_id: str, student_id: str) -> str: ...
    async def save_note(self, class_id: str, student_id: str, text: str) -> None: ...
    async def thresholds(self) -> list[int]: ...
    async def save_thresholds(self, percents: list[int]) -> None: ...


class PostgresRecords:
    async def note(self, class_id: str, student_id: str) -> str:
        async with sessions()() as session:
            row = await session.get(NoteRow, (class_id, student_id))
        return row.text if row else ""

    async def save_note(self, class_id: str, student_id: str, text: str) -> None:
        async with sessions().begin() as session:
            await session.execute(
                insert(NoteRow)
                .values(class_id=class_id, student_id=student_id, text=text)
                .on_conflict_do_update(
                    index_elements=["class_id", "student_id"],
                    set_={"text": text, "updated_at": func.now()},
                )
            )

    async def thresholds(self) -> list[int]:
        async with sessions()() as session:
            percents = await session.scalar(select(ThresholdsRow.percents))
        return list(percents) if percents else list(THRESHOLDS)

    async def save_thresholds(self, percents: list[int]) -> None:
        async with sessions().begin() as session:
            await session.execute(
                insert(ThresholdsRow)
                .values(id=True, percents=percents)
                .on_conflict_do_update(index_elements=["id"], set_={"percents": percents})
            )


def backend() -> Records:
    return PostgresRecords()
