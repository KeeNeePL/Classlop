"""Invented Items for the demo school, written by `write_demo_items` for the demo-school script."""

import uuid

from classlop.items.curriculum import curriculum
from classlop.items.records import create_item
from classlop.items.types import Difficulty, ItemContent

DIFFICULTIES: tuple[Difficulty, ...] = ("easy", "medium", "hard")
SECTIONS = 3


async def write_demo_items(per_cell: int = 4) -> list[uuid.UUID]:
    """`per_cell` closed Items for each of the first Curriculum sections at each Difficulty."""
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
                ids.append(await create_item(content, origin="chat"))
    return ids
