"""Invented Items for the demo school, written by `write_demo_items` for the demo-school script."""

import uuid

from sqlalchemy import delete, select

from classlop.items.curriculum import curriculum
from classlop.items.models import ItemRow, UsageRow
from classlop.items.records import create_item, retire_item
from classlop.items.types import Difficulty, ItemContent
from classlop.shared.db import sessions

DIFFICULTIES: tuple[Difficulty, ...] = ("easy", "medium", "hard")
SECTIONS = 3
ORIGIN_REF = "demo"


async def write_demo_items(per_cell: int = 4) -> list[uuid.UUID]:
    """`per_cell` closed Items for each of the first Curriculum sections at each Difficulty. Every
    Class and Assignment of the demo school is rewritten, so nothing is Given any more; Items
    from an earlier run are kept, as versions cannot be deleted."""
    expected = SECTIONS * len(DIFFICULTIES) * per_cell
    async with sessions().begin() as session:
        await session.execute(delete(UsageRow))
        kept = list(
            await session.scalars(
                select(ItemRow.id)
                .where(ItemRow.origin_ref == ORIGIN_REF, ItemRow.retired.is_(False))
                .order_by(ItemRow.created_at, ItemRow.id)
            )
        )
    if len(kept) == expected:
        return kept
    for item_id in kept:
        await retire_item(item_id)
    ids = []
    for section in curriculum()[:SECTIONS]:
        for difficulty in DIFFICULTIES:
            for n in range(1, per_cell + 1):
                content = ItemContent(
                    item_format="closed",
                    text=f"Zadanie demo {n} ({section.id}, {difficulty}): ile to {n}+{n}?",
                    points=1,
                    difficulty=difficulty,
                    curriculum_topics=[section.topics[0]],
                    general_requirements=["I"],
                    options={
                        "A": f"${n}$",
                        "B": f"${2 * n}$",
                        "C": f"${3 * n}$",
                        "D": f"${4 * n}$",
                    },
                    correct_options=["B"],
                )
                ids.append(await create_item(content, origin="chat", origin_ref=ORIGIN_REF))
    return ids
