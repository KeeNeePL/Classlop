import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

ItemFormat = Literal["closed", "open"]
Difficulty = Literal["easy", "medium", "hard"]
GeneralRequirement = Literal["I", "II", "III", "IV"]
Origin = Literal["generated", "uploaded"]
# Why the AI wants the Teacher's attention.
Flag = Literal["no_exemplar", "failed_tag_check", "unsure_extraction"]


class RubricLevel(BaseModel):
    points: int
    description: str


class CurriculumTopic(BaseModel):
    # Such as "lo2024:II.5"; the section is "II".
    id: str
    # Polish, as the Student reads it under "Do powtórki".
    name: str

    @property
    def section(self) -> str:
        return self.id.split(":")[-1].split(".")[0]


class ItemContent(BaseModel):
    """What the Item says; mathematics as inline LaTeX."""

    item_format: ItemFormat
    # Sub-parts inside.
    text: str
    points: int
    # Closed Items: option label (A-D, P/F) to its text, and the correct labels.
    options: dict[str, str] = {}
    correct_options: list[str] = []
    # Open Items.
    answer: str | None = None
    model_solution: str | None = None
    # Open Items: CKE levels, lowest first.
    rubric: list[RubricLevel] = []


class Tags(BaseModel):
    difficulty: Difficulty
    curriculum_topics: list[CurriculumTopic]
    general_requirements: list[GeneralRequirement]
    # The tagger's probability per tag, such as {"difficulty:medium": 0.8}.
    probabilities: dict[str, float] = {}


class ItemVersion(ItemContent):
    """A frozen Item: Assignments pin these, and they never change."""

    id: uuid.UUID
    item_id: uuid.UUID
    difficulty: Difficulty
    curriculum_topics: list[CurriculumTopic] = []
    general_requirements: list[GeneralRequirement] = []


class Item(BaseModel):
    id: uuid.UUID
    version: ItemVersion
    origin: Origin
    # An uploaded Item's file in S3 and its page, counted from 1.
    source_key: str | None = None
    source_page: int | None = None
    exemplar_ids: list[str] = []
    flag: Flag | None = None
    retired: bool = False
    created_at: datetime


class Usage(BaseModel):
    assignment_id: uuid.UUID
    class_id: str
    version_id: uuid.UUID
    given_at: datetime


class ItemFilters(BaseModel):
    """Each list matches any of its values; Retired items only show when asked for."""

    curriculum_topics: list[str] = []
    curriculum_sections: list[str] = []
    general_requirements: list[GeneralRequirement] = []
    difficulty: list[Difficulty] = []
    item_format: ItemFormat | None = None
    flagged: bool | None = None
    origin: Origin | None = None
    retired: bool = False
    never_used_with_class: str | None = None


class SearchPage(BaseModel):
    items: list[Item]
    total: int
    page: int


class Count(BaseModel):
    curriculum_section: str
    difficulty: Difficulty
    count: int
