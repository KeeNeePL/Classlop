"""The `grading` interface, driven as `teams` drives it: a fake LLM and a fake `items`,
real Postgres and S3 from compose, and the job queue read back for the upward event."""

import asyncio
import base64
import io
import json
import os
import uuid
from datetime import UTC, datetime

import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from PIL import Image
from pydantic import Field
from sqlalchemy import select

from classlop import grading, items
from classlop.items import ItemVersion
from classlop.shared import llm, queue, storage
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job

AI_LINE = "Ocena i komentarz przygotowane przez AI; nauczyciel sprawdza je wyrywkowo."


@pytest.fixture(scope="module", autouse=True)
async def stack():
    try:
        await asyncio.to_thread(migrate)
        await asyncio.to_thread(queue.url)
        await asyncio.to_thread(storage.ping)
    except Exception:
        if os.environ.get("CI"):
            raise
        pytest.skip("compose stand-ins are not running: docker compose up -d postgres elasticmq s3")


class Recording(GenericFakeChatModel):
    seen: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, stop, run_manager, **kwargs)


class FakeLLM:
    """Scripted Transcription replies at `shared.llm`; records what the model was sent."""

    def __init__(self, monkeypatch):
        self.keys: list[str] = []
        self.model = Recording(messages=iter([]))
        monkeypatch.setattr(llm, "chat_model", self._chat_model)

    def _chat_model(self, key):
        self.keys.append(key)
        return self.model

    def transcribes(self, *readings: dict) -> None:
        reply = AIMessage(json.dumps({"items": list(readings)}))
        self.model = Recording(messages=iter([reply]))

    def sent(self) -> list[dict]:
        return [part for messages in self.model.seen for m in messages for part in parts(m)]

    def prompt(self) -> str:
        return "\n".join(p["text"] for p in self.sent() if p["type"] == "text")

    def images(self) -> list[Image.Image]:
        return [
            Image.open(io.BytesIO(base64.b64decode(p["image_url"]["url"].split(",", 1)[1])))
            for p in self.sent()
            if p["type"] == "image_url"
        ]


def parts(message) -> list[dict]:
    content = message.content
    return [{"type": "text", "text": content}] if isinstance(content, str) else content


@pytest.fixture
def fake_llm(monkeypatch):
    return FakeLLM(monkeypatch)


@pytest.fixture
def bank(monkeypatch):
    """The fake `items`: frozen Item versions by ID."""
    versions: dict[uuid.UUID, ItemVersion] = {}

    async def get_versions(ids):
        return [versions[i] for i in ids]

    monkeypatch.setattr(items, "get_versions", get_versions)
    return versions


def read(number, reading="readable", chosen=None, transcription="", drawing=False) -> dict:
    return {
        "number": number,
        "transcription": transcription,
        "reading": reading,
        "drawing": drawing,
        "chosen_option": chosen,
    }


def closed(points=1, correct="B") -> ItemVersion:
    return ItemVersion(
        id=uuid.uuid4(),
        item_format="closed",
        text="Wartość wyrażenia $2^3 - 6$ jest równa:",
        points=points,
        options={"A": "$1$", "B": "$2$", "C": "$4$", "D": "$8$"},
        correct_options=[correct],
    )


def photo(size=(1200, 1600), exif: Image.Exif | None = None) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "JPEG", exif=exif or Image.Exif())
    return out.getvalue()


async def hand_in(bank, assignment: list[ItemVersion], pages: list[bytes] | None = None):
    """Run `grading.grade` as `teams` enqueues it; returns the hand-in's key."""
    submission_id, handed_in_at = uuid.uuid4(), datetime.now(UTC)
    keys = []
    for n, page in enumerate(pages or [photo()], 1):
        key = f"teams/hand-ins/{submission_id}/page-{n}.jpg"
        await asyncio.to_thread(storage.put, key, page, "image/jpeg")
        keys.append(key)
    for item in assignment:
        bank[item.id] = item
    payload = {
        "submission_id": str(submission_id),
        "handed_in_at": handed_in_at.isoformat(),
        "items": [{"id": str(i.id), "number": n} for n, i in enumerate(assignment, 1)],
        "files": keys,
    }

    async def progress(value):
        pass

    job = Job(id=uuid.uuid4(), kind="grading.grade", payload=payload, attempts=1)
    await grading.grade(job, progress)
    return submission_id, handed_in_at


async def graded_events(submission_id) -> list[dict]:
    async with sessions()() as session:
        jobs = await session.scalars(select(Job).where(Job.kind == "teams.submission_graded"))
        return [j.payload for j in jobs if j.payload["submission_id"] == str(submission_id)]


async def test_a_correct_closed_item_scores_full_points_and_teams_is_told_once(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    submission_id, handed_in_at = await hand_in(bank, [closed(points=2, correct="B")])

    result = await grading.result(submission_id, handed_in_at)
    assert result is not None
    assert result.status == "graded"
    assert [
        (i.number, i.ai_points, i.points, i.max_points, i.reading, i.drawing, i.ai_transcription)
        for i in result.items
    ] == [(1, 2, 2, 2, "readable", False, "B")]
    assert (result.held, result.held_reasons, result.spot_check) == (False, [], False)
    assert result.comment == f"Zadanie 1: 2/2 pkt – poprawnie\n\n{AI_LINE}"
    assert await graded_events(submission_id) == [
        {"submission_id": str(submission_id), "handed_in_at": handed_in_at.isoformat()}
    ]


async def test_a_wrong_option_scores_nothing(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="C", transcription="C"))

    result = await grading.result(*await hand_in(bank, [closed(points=1, correct="B")]))

    assert result is not None
    assert [(i.ai_points, i.reading) for i in result.items] == [(0, "readable")]
    assert not result.held
    assert result.comment == f"Zadanie 1: 0/1 pkt – błędna odpowiedź\n\n{AI_LINE}"


async def test_the_model_sees_the_option_values_but_never_the_key(bank, fake_llm):
    # The same Item under two keys must make the same prompt.
    prompts = []
    item = closed(correct="B")
    for key in ("B", "D"):
        fake_llm.transcribes(read(1, chosen="B", transcription="B"))
        await hand_in(bank, [item.model_copy(update={"correct_options": [key]})])
        prompts.append(fake_llm.prompt())

    assert prompts[0] == prompts[1]
    assert all(value in prompts[0] for value in item.options.values())


async def test_an_unsure_choice_holds_the_submission_and_names_the_items(bank, fake_llm):
    fake_llm.transcribes(
        read(1, chosen="B", transcription="B"),
        # Two options marked, or an unclear crossing-out: the model reports unsure.
        read(2, reading="unsure", transcription="B [przekreślone: C]"),
        # Something written, but no option chosen.
        read(3, chosen=None, transcription="7"),
        # A label that is not one of the options.
        read(4, chosen="E", transcription="E"),
        # Item 5 is missing from the reply.
    )

    result = await grading.result(*await hand_in(bank, [closed() for _ in range(5)]))

    assert result is not None
    assert [(i.number, i.reading, i.ai_points) for i in result.items] == [
        (1, "readable", 1),
        (2, "unsure", 0),
        (3, "unsure", 0),
        (4, "unsure", 0),
        (5, "unsure", 0),
    ]
    assert result.held
    assert [r.model_dump() for r in result.held_reasons] == [
        {"reason": "niepewny odczyt", "items": [2, 3, 4, 5]}
    ]
    assert result.spot_check
    assert result.spot_check_reasons == result.held_reasons


async def test_an_unreadable_item_scores_nothing_and_holds_the_submission(bank, fake_llm):
    fake_llm.transcribes(
        read(1, reading="unreadable", transcription="[nieczytelne]"),
        read(2, reading="unsure", chosen="B", transcription="B"),
    )

    result = await grading.result(*await hand_in(bank, [closed(), closed()]))

    assert result is not None
    assert [(i.reading, i.ai_points) for i in result.items] == [("unreadable", 0), ("unsure", 1)]
    assert [r.model_dump() for r in result.held_reasons] == [
        {"reason": "nieczytelne", "items": [1]},
        {"reason": "niepewny odczyt", "items": [2]},
    ]
    assert result.comment == (
        "Zadanie 1: 0/1 pkt – nie udało się odczytać rozwiązania\n"
        f"Zadanie 2: 1/1 pkt – poprawnie\n\n{AI_LINE}"
    )


async def test_a_blank_item_scores_nothing_and_does_not_hold(bank, fake_llm):
    fake_llm.transcribes(
        read(1, chosen="B", transcription="B"),
        read(2, reading="blank", chosen="B", transcription="Z. 2"),
    )

    result = await grading.result(*await hand_in(bank, [closed(points=2), closed()]))

    assert result is not None
    assert [(i.reading, i.ai_points, i.ai_transcription) for i in result.items] == [
        ("readable", 2, "B"),
        ("blank", 0, ""),
    ]
    assert (result.held, result.spot_check) == (False, False)
    assert result.comment == (
        f"Zadanie 1: 2/2 pkt – poprawnie\nZadanie 2: 0/1 pkt – brak rozwiązania\n\n{AI_LINE}"
    )


async def test_transcription_uses_its_configured_model_and_never_invents_work(bank, fake_llm):
    fake_llm.transcribes(read(1, reading="blank"))

    await hand_in(bank, [closed()])

    assert fake_llm.keys == ["grading.transcribe"]
    # The prototype invented an answer from a bare "Z. 1".
    assert "Transcribe nothing where nothing is written" in fake_llm.prompt()


async def test_pages_reach_the_model_upright_and_downscaled(bank, fake_llm):
    sideways = Image.Exif()
    sideways[0x0112] = 6  # EXIF Orientation: rotate 90 degrees clockwise to view.
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    await hand_in(bank, [closed()], pages=[photo((4000, 3000), sideways), photo((800, 600))])

    assert [i.size for i in fake_llm.images()] == [(1500, 2000), (800, 600)]
