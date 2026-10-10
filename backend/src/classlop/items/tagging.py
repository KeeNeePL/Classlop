"""Tags an Exemplar's or Item's text with Jev (TypeSafe's System One classifier) through its
official API: one Choice for the Curriculum section, a Noul per topic of the likely section(s),
a Choice for the General requirement and a Score for Difficulty."""

from typing import Any, Protocol

from jevper import AsyncSystemOneClient, Choice, Noul, Score
from langsmith import traceable
from openai import AsyncOpenAI

from classlop.items.curriculum import CurriculumTopic, curriculum, general_requirements
from classlop.items.types import Difficulty, Tags
from classlop.shared.settings import get_settings

TAG_AT = 0.5
SECOND_SECTION_AT = 0.25
DIFFICULTIES: tuple[Difficulty, ...] = ("easy", "medium", "hard")
# Jev reads the text as given: Polish exercises, so the definitions are Polish too.
DIFFICULTY_LEVELS = [
    "Zadanie łatwe: jedno znane działanie lub wzór, rozwiązanie w jednym-dwóch krokach.",
    "Zadanie średnie: kilka kroków lub połączenie dwóch znanych metod.",
    "Zadanie trudne: wymaga pomysłu, wielu kroków albo połączenia kilku działów.",
]


class Tagged(Tags):
    """Tags with the probabilities Jev gave: per question, option to probability."""

    probabilities: dict[str, dict[str, float]] = {}


class Tagger(Protocol):
    async def tag(self, text: str) -> Tags: ...


class JevTagger:
    def __init__(self, client: Any):
        self._client = client

    @traceable(name="items.tag")
    async def tag(self, text: str) -> Tagged:
        sections = {s.id: s for s in curriculum()}
        general = {g.id: g.description for g in general_requirements()}
        first = await self._client.system_one(
            state=text,
            questions={
                "section": Choice(
                    instructions="Do którego działu podstawy programowej należy zadanie?",
                    criteria={s.id: s.name for s in sections.values()},
                ),
                "general": Choice(
                    instructions="Którą umiejętność ogólną sprawdza zadanie?",
                    criteria=general,
                ),
                "difficulty": Score(
                    instructions="Jak trudne jest zadanie dla ucznia liceum?",
                    criteria=DIFFICULTY_LEVELS,
                ),
            },
        )
        ranked = sorted(
            first.answers["section"].probabilities.items(), key=lambda kv: kv[1], reverse=True
        )
        asked = [sections[ranked[0][0]]]
        if len(ranked) > 1 and ranked[1][1] > SECOND_SECTION_AT:
            asked.append(sections[ranked[1][0]])
        topic_names = {t.id: t.name for s in asked for t in s.topics}
        second = await self._client.system_one(
            state=text,
            questions={
                tid: Noul(instructions=f"Czy zadanie sprawdza umiejętność: {name}?")
                for tid, name in topic_names.items()
            },
        )
        scores = {tid: second.answers[tid].noul for tid in topic_names}
        chosen = [tid for tid, p in scores.items() if p >= TAG_AT]
        if not chosen:
            chosen = [max(asked[0].topics, key=lambda t: scores[t.id]).id]
        difficulty = first.answers["difficulty"].probabilities
        return Tagged(
            difficulty=DIFFICULTIES[int(first.answers["difficulty"].score)],
            curriculum_topics=[
                CurriculumTopic(id=tid, name=topic_names[tid])
                for tid in topic_names
                if tid in chosen
            ],
            general_requirements=[first.answers["general"].choice],
            probabilities={
                "section": dict(ranked),
                "curriculum_topics": scores,
                "general_requirements": dict(first.answers["general"].probabilities),
                "difficulty": {d: difficulty[i] for i, d in enumerate(DIFFICULTIES)},
            },
        )


def default_tagger() -> Tagger:
    settings = get_settings()
    if settings.typesafe_api_key is None:
        raise RuntimeError("TYPESAFE_API_KEY is not set")
    openai = AsyncOpenAI(
        base_url=settings.typesafe_base_url, api_key=settings.typesafe_api_key.get_secret_value()
    )
    return JevTagger(AsyncSystemOneClient(openai, model="jev-latest", api="systemone"))
