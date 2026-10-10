from types import SimpleNamespace

from classlop.items.curriculum import curriculum
from classlop.items.tagging import JevTagger

SECTIONS = curriculum()
FIRST, SECOND = SECTIONS[0], SECTIONS[1]


class FakeJev:
    """Answers System One calls from canned per-question answers; records the questions."""

    def __init__(self, section_probs, noul=None, general="II", difficulty=(0.1, 0.7, 0.2)):
        self.section_probs = section_probs
        self.noul = noul or {}
        self.general = general
        self.difficulty = difficulty
        self.calls: list[dict] = []

    async def system_one(self, *, state, questions, **_):
        self.calls.append({"state": state, "questions": questions})
        answers = {}
        for key in questions:
            if key == "section":
                best = max(self.section_probs, key=self.section_probs.get)
                answers[key] = SimpleNamespace(choice=best, probabilities=self.section_probs)
            elif key == "general":
                answers[key] = SimpleNamespace(
                    choice=self.general, probabilities={self.general: 0.9}
                )
            elif key == "difficulty":
                probs = dict(enumerate(self.difficulty))
                answers[key] = SimpleNamespace(
                    score=probs and max(probs, key=lambda k: probs[k]), probabilities=probs
                )
            else:
                answers[key] = SimpleNamespace(noul=self.noul.get(key, 0.0))
        return SimpleNamespace(answers=answers)


def topic_keys(section, *probs):
    return {t.id: p for t, p in zip(section.topics, probs, strict=False)}


async def test_tags_the_topics_at_half_or_more_in_the_top_section():
    jev = FakeJev({FIRST.id: 0.9, SECOND.id: 0.1}, topic_keys(FIRST, 0.8, 0.2, 0.5))
    tags = await JevTagger(jev).tag("Oblicz $2+2$.")
    assert [t.id for t in tags.curriculum_topics] == [FIRST.topics[0].id, FIRST.topics[2].id]
    assert tags.general_requirements == ["II"]
    assert tags.difficulty == "medium"
    assert tags.probabilities["difficulty"] == {"easy": 0.1, "medium": 0.7, "hard": 0.2}
    assert tags.probabilities["curriculum_topics"][FIRST.topics[1].id] == 0.2


async def test_the_top_topic_is_kept_when_none_reaches_half():
    jev = FakeJev({FIRST.id: 1.0}, topic_keys(FIRST, 0.1, 0.4, 0.3))
    tags = await JevTagger(jev).tag("x")
    assert [t.id for t in tags.curriculum_topics] == [FIRST.topics[1].id]


async def test_the_second_section_is_asked_too_when_above_a_quarter():
    noul = {**topic_keys(FIRST, 0.9), **topic_keys(SECOND, 0.6)}
    jev = FakeJev({FIRST.id: 0.6, SECOND.id: 0.3, SECTIONS[2].id: 0.1}, noul)
    tags = await JevTagger(jev).tag("x")
    assert {t.id for t in tags.curriculum_topics} == {FIRST.topics[0].id, SECOND.topics[0].id}


async def test_the_second_section_is_left_out_at_a_quarter_or_less():
    jev = FakeJev({FIRST.id: 0.75, SECOND.id: 0.25}, topic_keys(FIRST, 0.9))
    await JevTagger(jev).tag("x")
    asked = jev.calls[1]["questions"]
    assert set(asked) == {t.id for t in FIRST.topics}
