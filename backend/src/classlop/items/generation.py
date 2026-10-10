"""The Generation graph: one worker job per Generation request, one branch per Item. A branch
retrieves Exemplars (filter, hybrid top 20, LLM rerank to a few), writes the Item in one
generation pass, tags it, checks the tags and the near-duplicate rule, and regenerates on a
failure; the last of three attempts enters the bank as a Flagged item. Graph state holds ids
only, and each Item commits on its own."""

import json
import operator
import uuid
from collections import Counter
from typing import Annotated, Literal, Self, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field, ValidationError, model_validator
from sqlalchemy import select

from classlop.items import embedding, exemplars, index, records, tagging
from classlop.items.curriculum import curriculum
from classlop.items.models import ExemplarRow
from classlop.items.types import Difficulty, ItemContent, ItemFormat, RubricLevel
from classlop.shared import jobs, llm
from classlop.shared.db import sessions
from classlop.shared.jobs import Progress
from classlop.shared.search import client
from classlop.shared.settings import get_settings

MAX_ATTEMPTS = 3
DUPLICATE_COSINE = 0.93  # tuned later
CANDIDATES = 20
KEEP = 4  # Exemplars a branch models on: 3-5
WEAK_RERANK = 0.3
SPREAD_PENALTY = 0.2  # per earlier branch that already took the Exemplar
PARALLEL_BRANCHES = 5
NO_EXEMPLAR = "brak wzorca"

GENERATE = """Jesteś autorem zadań z matematyki dla liceum (poziom podstawowy, podstawa 2024).
Napisz jedno nowe zadanie w stylu podanych wzorców, ale nie kopiuj ich. Cała matematyka to
LaTeX w znakach $. Zadanie zamknięte: options (A-D) i correct_options, bez answer, rubric.
Zadanie otwarte: answer, model_solution i rubric jako poziomy punktacji CKE rosnące do points,
bez options."""
RERANK = """Oceń, jak dobrym wzorcem dla nowego zadania jest każdy kandydat: score od 0 do 1.
Zwróć score dla każdego id."""


class Line(BaseModel):
    """Count Items of one kind; `curriculum_section` is set on a Nowa praca shortfall line."""

    count: int = Field(ge=1)
    difficulty: Difficulty
    item_format: ItemFormat
    curriculum_topics: list[str] = []
    curriculum_section: str | None = None


class GenerationSpec(BaseModel):
    lines: list[Line] = Field(min_length=1)
    level: Literal["basic", "extended"] = "basic"


class GenerationOrigin(BaseModel):
    """A Chat, or Nowa praca plus the Class it plans for."""

    kind: Literal["chat", "nowa_praca"]
    chat_id: str | None = None
    class_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _names_its_source(self) -> Self:
        if self.ref is None:
            raise ValueError(f"a {self.kind} origin needs its id")
        return self

    @property
    def ref(self) -> str | None:
        return self.chat_id if self.kind == "chat" else str(self.class_id or "") or None


class Request(BaseModel):
    spec: GenerationSpec
    origin: GenerationOrigin


class Draft(BaseModel):
    """What one generation pass writes; the tags come from the tagger."""

    item_format: ItemFormat
    text: str
    points: int
    options: dict[str, str] = {}
    correct_options: list[str] = []
    answer: str | None = None
    model_solution: str | None = None
    rubric: list[RubricLevel] = []


class Score(BaseModel):
    id: str
    score: float


class Ranking(BaseModel):
    scores: list[Score]


class ItemTask(TypedDict):
    line: int
    slot: int
    spec: Line
    # The Curriculum topic this Item is asked to cover, spread over the line's topics.
    topic: str | None


class BranchInput(TypedDict):
    task: ItemTask


class BranchState(BranchInput, total=False):
    exemplar_ids: list[str]
    no_exemplar: bool
    attempts: int
    candidate: ItemContent | None
    problems: list[str]
    item_id: uuid.UUID


class State(TypedDict, total=False):
    landed: Annotated[dict[str, str], operator.or_]


async def request_generation(spec: GenerationSpec, origin: GenerationOrigin) -> uuid.UUID:
    """Queue one job for the Generation request; its result lists the Item ids per line."""
    if spec.level != "basic":
        raise ValueError("Classlop generates Items at basic level only")
    return await jobs.enqueue(
        "items.generate", Request(spec=spec, origin=origin).model_dump(mode="json")
    )


async def _exemplar_texts(ids: list[str]) -> list[dict]:
    async with sessions()() as session:
        rows = await session.scalars(select(ExemplarRow).where(ExemplarRow.id.in_(ids)))
        return [
            {"text": r.text, "answer": r.answer, "solution": r.solution}
            for r in sorted(rows, key=lambda r: ids.index(r.id))
        ]


async def _nearest_cosine(content: ItemContent) -> float:
    """Cosine of the closest live Item in the bank; k-NN scores (1 + cosine) / 2."""
    vector = (await embedding.embed([index.searchable_text(content)]))[0]
    await index.create_index()
    result = await client().search(
        index=get_settings().items_index,
        body={
            "size": 1,
            "_source": False,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": vector,
                        "k": 1,
                        "filter": {"bool": {"filter": [{"term": {"retired": False}}]}},
                    }
                }
            },
        },
    )
    hits = result["hits"]["hits"]
    return 2 * hits[0]["_score"] - 1 if hits else -1.0


class Run:
    def __init__(self, request: Request, progress: Progress, tagger: tagging.Tagger):
        self.request, self.progress, self.tagger = request, progress, tagger
        self.total = sum(line.count for line in request.spec.lines)
        # Exemplars the branches took so far, so the batch spreads over them.
        self.claimed: Counter[str] = Counter()
        self.landed = 0

    def fan_out(self, _: State) -> list[Send]:
        return [
            Send(
                "item",
                {
                    "task": ItemTask(
                        line=i,
                        slot=n,
                        spec=line,
                        topic=line.curriculum_topics[n % len(line.curriculum_topics)]
                        if line.curriculum_topics
                        else None,
                    )
                },
            )
            for i, line in enumerate(self.request.spec.lines)
            for n in range(line.count)
        ]

    async def item(self, state: BranchState) -> dict:
        end = await self.branch().ainvoke(state)
        item_id = end.get("item_id")
        task = state["task"]
        return {"landed": {f"{task['line']}:{task['slot']}": item_id}} if item_id else {}

    def branch(self):
        return (
            StateGraph(BranchState)
            .add_node(self.retrieve)
            .add_node(self.attempt)
            .add_node(self.land)
            .add_edge(START, "retrieve")
            .add_edge("retrieve", "attempt")
            .add_conditional_edges("attempt", self.settled, ["attempt", "land"])
            .add_edge("land", END)
            .compile()
        )

    async def retrieve(self, state: BranchState) -> dict:
        task = state["task"]
        line = task["spec"]
        topics = {t.id: t.name for s in curriculum() for t in s.topics}
        sections = (
            [line.curriculum_section]
            if line.curriculum_section
            else sorted({index.section_of(t) for t in line.curriculum_topics})
        )
        query = topics.get(task["topic"] or "") or next(
            (s.name for s in curriculum() if s.id in sections), "zadanie z matematyki"
        )
        found: list[exemplars.Exemplar] = []
        levels: list[list[Difficulty] | None] = [[line.difficulty], None]
        for difficulty in levels:
            found = await exemplars.search_exemplars(
                query,
                curriculum_sections=sections or None,
                difficulty=difficulty,
                size=CANDIDATES,
            )
            if found:
                break
        if not found:
            return {"exemplar_ids": [], "no_exemplar": True}
        ranking = await llm.ask(
            "items.rerank",
            Ranking,
            [
                SystemMessage(RERANK),
                HumanMessage(
                    json.dumps(
                        {
                            "zadanie": f"{query}, trudność {line.difficulty}",
                            "kandydaci": [{"id": e.id, "text": e.text} for e in found],
                        },
                        ensure_ascii=False,
                    )
                ),
            ],
        )
        raw = {s.id: s.score for s in ranking.scores}
        adjusted = {e.id: raw.get(e.id, 0) - SPREAD_PENALTY * self.claimed[e.id] for e in found}
        chosen = sorted(adjusted, key=lambda i: adjusted[i], reverse=True)[:KEEP]
        self.claimed.update(chosen)
        return {"exemplar_ids": chosen, "no_exemplar": max(raw.values(), default=0) < WEAK_RERANK}

    async def attempt(self, state: BranchState) -> dict:
        task = state["task"]
        line = task["spec"]
        attempts = state.get("attempts", 0) + 1
        brief = {
            "item_format": line.item_format,
            "difficulty": line.difficulty,
            "curriculum_topic": task["topic"],
            "curriculum_section": line.curriculum_section,
            "wzorce": await _exemplar_texts(state.get("exemplar_ids", [])),
            "poprzednia_próba_odrzucona_bo": state.get("problems", []),
        }
        draft = await llm.ask(
            "items.generate",
            Draft,
            [SystemMessage(GENERATE), HumanMessage(json.dumps(brief, ensure_ascii=False))],
        )
        shown = "\n".join([draft.text, *draft.options.values()])
        tags = await self.tagger.tag(shown)
        try:
            content = ItemContent.model_validate(
                draft.model_dump()
                | {
                    f: getattr(tags, f)
                    for f in ("difficulty", "curriculum_topics", "general_requirements")
                }
            )
        except ValidationError as error:
            return {
                "attempts": attempts,
                "problems": [f"nieprawidłowe zadanie: {error.error_count()} błędów"],
            }
        problems = []
        if draft.item_format != line.item_format:
            problems.append(f"format {draft.item_format}, oczekiwano {line.item_format}")
        if content.difficulty != line.difficulty:
            problems.append(f"trudność {content.difficulty}, oczekiwano {line.difficulty}")
        tagged = {t.id for t in content.curriculum_topics}
        if task["topic"] and task["topic"] not in tagged:
            problems.append(f"brak tematu {task['topic']} wśród tagów")
        if line.curriculum_section and line.curriculum_section not in {
            index.section_of(t) for t in tagged
        }:
            problems.append(f"tagi poza działem {line.curriculum_section}")
        if not problems and await _nearest_cosine(content) > DUPLICATE_COSINE:
            problems.append("zbyt podobne do istniejącego zadania")
        return {"attempts": attempts, "candidate": content, "problems": problems}

    def settled(self, state: BranchState) -> Literal["attempt", "land"]:
        if not state.get("problems") or state.get("attempts", 0) >= MAX_ATTEMPTS:
            return "land"
        return "attempt"

    async def land(self, state: BranchState) -> dict:
        content = state.get("candidate")
        if content is None:
            return {}
        reasons = [*state.get("problems", []), *([NO_EXEMPLAR] if state.get("no_exemplar") else [])]
        origin = self.request.origin
        item_id = await records.create_item(
            content,
            origin=origin.kind,
            origin_ref=origin.ref,
            exemplar_ids=state.get("exemplar_ids", []),
            flag_reason="; ".join(reasons) or None,
        )
        # Searchable now, so a sibling branch's near-duplicate check sees this Item.
        await index.reindex(item_id)
        await client().indices.refresh(index=get_settings().items_index)
        self.landed += 1
        await self.progress({"landed": self.landed, "total": self.total})
        return {"item_id": item_id}

    async def run(self) -> dict:
        graph = (
            StateGraph(State)
            .add_node("item", self.item)
            .add_conditional_edges(START, self.fan_out, ["item"])
            .add_edge("item", END)
            .compile()
        )
        end = await graph.ainvoke({"landed": {}}, {"max_concurrency": PARALLEL_BRANCHES})
        return {
            "lines": [
                [
                    str(end["landed"][key])
                    for n in range(line.count)
                    if (key := f"{i}:{n}") in end["landed"]
                ]
                for i, line in enumerate(self.request.spec.lines)
            ]
        }


async def generate(request: Request, progress: Progress) -> dict:
    await progress({"landed": 0, "total": sum(line.count for line in request.spec.lines)})
    return await Run(request, progress, tagging.default_tagger()).run()
