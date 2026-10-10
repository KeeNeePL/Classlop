import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

Difficulty = Literal["easy", "medium", "hard"]
GeneralRequirement = Literal["I", "II", "III", "IV"]
ItemFormat = Literal["closed", "open"]
# Where an Item came from: a Chat generation request, a Chat Item upload, or the shortfall of a
# Nowa praca.
Origin = Literal["chat", "upload", "nowa_praca"]
# The tags a Teacher can set by hand and a re-tag then leaves alone.
TagField = Literal["difficulty", "curriculum_topics", "general_requirements"]


class RubricLevel(BaseModel):
    points: int
    description: str


class CurriculumTopic(BaseModel):
    id: str
    name: str  # Polish, as the Student reads it


class Tags(BaseModel):
    difficulty: Difficulty
    curriculum_topics: list[CurriculumTopic] = Field(min_length=1)
    general_requirements: list[GeneralRequirement] = Field(min_length=1)


class ItemContent(Tags):
    """What a version says; all mathematics is inline LaTeX."""

    item_format: ItemFormat
    text: str
    points: int = Field(ge=0)
    # Closed Items: option label (A-D, P/F) to its text, and the correct labels.
    options: dict[str, str] = {}
    correct_options: list[str] = []
    # Open Items: CKE levels, lowest first.
    answer: str | None = None
    rubric: list[RubricLevel] = []
    model_solution: str | None = None

    @model_validator(mode="after")
    def _fits_format(self) -> Self:
        if self.item_format == "closed":
            if not self.options or not self.correct_options:
                raise ValueError("a closed Item needs options and correct options")
            if not set(self.correct_options) <= set(self.options):
                raise ValueError("a correct option is not one of the options")
            if self.rubric or self.answer is not None:
                raise ValueError("a closed Item has no answer or Rubric")
        else:
            if self.options or self.correct_options:
                raise ValueError("an open Item has no options")
            if self.answer is None or self.model_solution is None or not self.rubric:
                raise ValueError("an open Item needs an answer, a Model solution and a Rubric")
            levels = [level.points for level in self.rubric]
            if levels != sorted(set(levels)) or levels[-1] > self.points:
                raise ValueError("Rubric levels rise to at most the Item's points")
        return self


class ItemVersion(ItemContent):
    """An immutable version of an Item, as Assignments pin it."""

    id: uuid.UUID
    item_id: uuid.UUID
    number: int
    created_at: datetime


class Item(BaseModel):
    """An Item's record with its current version."""

    id: uuid.UUID
    origin: Origin
    origin_ref: str | None
    source_file: str | None
    source_page: int | None
    exemplar_ids: list[str]
    flagged: bool
    flag_reason: str | None
    retired: bool
    created_at: datetime
    version: ItemVersion


class Usage(BaseModel):
    """An Item given to a Class in an Assignment, with the version pinned."""

    item_id: uuid.UUID
    version_id: uuid.UUID
    assignment_id: uuid.UUID
    class_id: uuid.UUID
    given_at: datetime


class Filters(BaseModel):
    """What narrows a search or a count; each list matches any of its values. Retired items are
    left out unless `retired` says otherwise."""

    difficulty: list[Difficulty] = []
    curriculum_topics: list[str] = []
    curriculum_sections: list[str] = []
    general_requirements: list[GeneralRequirement] = []
    item_format: ItemFormat | None = None
    origin: list[Origin] = []
    retired: bool | None = False
    flagged: bool | None = None
    used_with_class: uuid.UUID | None = None
    never_used_with_class: uuid.UUID | None = None


class SearchPage(BaseModel):
    items: list[Item]
    total: int
    page: int
    size: int


class SectionCount(BaseModel):
    """How many Items a Curriculum section has at one Difficulty."""

    section: str
    difficulty: Difficulty
    count: int
