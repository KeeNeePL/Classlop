import uuid
from typing import Literal

from pydantic import BaseModel


class RubricLevel(BaseModel):
    points: int
    description: str


class CurriculumTopic(BaseModel):
    id: str
    # Polish, as the Student reads it under "Do powtórki".
    name: str


class ItemVersion(BaseModel):
    """A frozen Item, as #31 defines the contract; only the fields grading reads so far."""

    id: uuid.UUID
    item_format: Literal["closed", "open"]
    text: str
    points: int
    # Closed Items: option label (A-D, P/F) to its text, and the correct labels.
    options: dict[str, str] = {}
    correct_options: list[str] = []
    model_solution: str | None = None
    # Open Items: CKE levels, lowest first.
    rubric: list[RubricLevel] = []
    curriculum_topics: list[CurriculumTopic] = []


async def get_versions(version_ids: list[uuid.UUID]) -> list[ItemVersion]:
    raise NotImplementedError("Item records arrive with #31")
