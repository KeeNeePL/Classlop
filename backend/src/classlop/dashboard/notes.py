"""The Notes the dashboard keeps. A Note lives and dies with its Class, which `teams` does not
know of, so the dashboard deletes them when it deletes the Class."""

from typing import Protocol

from sqlalchemy import delete

from classlop.dashboard.models import NoteRecord
from classlop.shared.db import sessions


class Notes(Protocol):
    async def delete_class(self, class_id: str) -> None: ...


class NoteTable:
    async def delete_class(self, class_id: str) -> None:
        async with sessions().begin() as session:
            await session.execute(delete(NoteRecord).where(NoteRecord.class_id == class_id))


def backend() -> Notes:
    return NoteTable()
