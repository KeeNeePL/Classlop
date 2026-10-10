"""The `grading` interface, driven as `teams` drives it: a fake LLM and a fake `items`,
real Postgres and S3 from compose, and the job queue read back for the upward event."""

import asyncio
import base64
import io
import json
import os
import uuid
from datetime import UTC, datetime

import pillow_heif
import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from PIL import Image
from pydantic import Field
from sqlalchemy import select

from classlop import grading, items
from classlop.items import CurriculumTopic, ItemVersion, RubricLevel
from classlop.shared import llm, queue, storage
from classlop.shared.db import sessions
from classlop.shared.migrate import migrate
from classlop.shared.models import Job

pillow_heif.register_heif_opener()

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
    # Scoring runs in parallel, so its replies are picked by the Item text in the prompt.
    by_text: dict[str, str] = Field(default_factory=dict)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(messages)
        if not self.by_text:
            return super()._generate(messages, stop, run_manager, **kwargs)
        prompt = text_of(messages)
        (reply,) = [r for text, r in self.by_text.items() if text in prompt]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(reply))])


class FakeLLM:
    """Scripted replies per config key at `shared.llm`; records what each model was sent."""

    def __init__(self, monkeypatch):
        self.keys: list[str] = []
        self.models: dict[str, Recording] = {}
        monkeypatch.setattr(llm, "chat_model", self._chat_model)

    def _chat_model(self, key):
        self.keys.append(key)
        return self.models[key]

    def transcribes(self, *transcriptions: dict) -> None:
        reply = AIMessage(json.dumps({"items": list(transcriptions)}))
        self.models["grading.transcribe"] = Recording(messages=iter([reply]))
        self.verifies(*(confirmed(t["number"]) for t in transcriptions))

    def verifies(self, *checks: dict) -> None:
        reply = AIMessage(json.dumps({"items": list(checks)}))
        self.models["grading.verify"] = Recording(messages=iter([reply]))

    def scores(self, by_text: dict[str, dict]) -> None:
        """The scoring reply for each open Item, by its text."""
        replies = {text: json.dumps(score) for text, score in by_text.items()}
        self.models["grading.score"] = Recording(messages=iter([]), by_text=replies)

    def prompt(self, key="grading.transcribe") -> str:
        return "\n".join(text_of(messages) for messages in self.models[key].seen)

    def images(self) -> list[Image.Image]:
        seen = self.models["grading.transcribe"].seen
        return [
            Image.open(io.BytesIO(base64.b64decode(p["image_url"]["url"].split(",", 1)[1])))
            for messages in seen
            for p in parts(messages)
            if p["type"] == "image_url"
        ]


def parts(messages) -> list[dict]:
    """Every content part of the messages; string content is one text part."""
    return [
        part
        for m in messages
        for part in (
            [{"type": "text", "text": m.content}] if isinstance(m.content, str) else m.content
        )
    ]


def text_of(messages) -> str:
    return "\n".join(p["text"] for p in parts(messages) if p["type"] == "text")


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


def frozen() -> dict:
    """The fields of a stored version that grading ignores."""
    return dict(
        id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        number=1,
        created_at=datetime(2026, 10, 1, tzinfo=UTC),
        difficulty="easy",
        curriculum_topics=[CurriculumTopic(id="lo2024:II.5", name="Równania kwadratowe")],
        general_requirements=["I"],
    )


def closed(points=1, correct="B") -> ItemVersion:
    return ItemVersion(
        **frozen(),
        item_format="closed",
        text="Wartość wyrażenia $2^3 - 6$ jest równa:",
        points=points,
        options={"A": "$1$", "B": "$2$", "C": "$4$", "D": "$8$"},
        correct_options=[correct],
    )


def open_item(text="Rozwiąż równanie $x^2 - 4x - 5 = 0$.", points=2) -> ItemVersion:
    return ItemVersion(
        **frozen(),
        answer=r"$x_1 = -1$, $x_2 = 5$",
        item_format="open",
        text=text,
        points=points,
        model_solution=r"$\Delta = 36$, $x_1 = -1$, $x_2 = 5$",
        rubric=[
            RubricLevel(points=1, description=r"Obliczenie $\Delta = 36$."),
            RubricLevel(points=2, description="Oba pierwiastki: $x_1 = -1$, $x_2 = 5$."),
        ],
    )


def confirmed(number) -> dict:
    return {"number": number, "verdict": "confirmed", "note": ""}


def disputed(number, note) -> dict:
    return {"number": number, "verdict": "disputed", "note": note}


def score(points, doubt=False, feedback="", mistake=None) -> dict:
    return {"points": points, "doubt": doubt, "feedback": feedback, "mistake": mistake}


def photo(size=(1200, 1600), exif: Image.Exif | None = None) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "JPEG", exif=exif or Image.Exif())
    return out.getvalue()


def heic(size=(1200, 1600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "HEIF")
    return out.getvalue()


def pdf(pages: int, size=(595, 842)) -> bytes:
    """An A4 PDF of blank pages, at 72 dpi."""
    out = io.BytesIO()
    first, *rest = [Image.new("RGB", size, "white") for _ in range(pages)]
    first.save(out, "PDF", save_all=True, append_images=rest, resolution=72)
    return out.getvalue()


async def hand_in(
    bank, assignment: list[ItemVersion], files: list[bytes] | None = None, deliveries: int = 1
):
    """Run `grading.grade` as `teams` enqueues it, as often as SQS delivers it; returns the
    hand-in's key."""
    submission_id, handed_in_at = uuid.uuid4(), datetime.now(UTC)
    keys = []
    for n, file in enumerate(files or [photo()], 1):
        # Named and typed as the Student's phone sent it; grading goes by content.
        key = f"teams/hand-ins/{submission_id}/file-{n}"
        await asyncio.to_thread(storage.put, key, file, "application/octet-stream")
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

    for attempt in range(1, deliveries + 1):
        job = Job(id=uuid.uuid4(), kind="grading.grade", payload=payload, attempts=attempt)
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

    assert fake_llm.keys == ["grading.transcribe", "grading.verify"]
    # The prototype invented an answer from a bare "Z. 1".
    assert "Transcribe nothing where nothing is written" in fake_llm.prompt()


async def test_pages_reach_the_model_upright_and_downscaled(bank, fake_llm):
    sideways = Image.Exif()
    sideways[0x0112] = 6  # EXIF Orientation: rotate 90 degrees clockwise to view.
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    await hand_in(bank, [closed()], files=[photo((4000, 3000), sideways), photo((800, 600))])

    assert [i.size for i in fake_llm.images()] == [(1500, 2000), (800, 600)]


async def test_an_open_item_is_scored_against_its_rubric(bank, fake_llm):
    item = open_item(points=2)
    fake_llm.transcribes(read(1, transcription="\\Delta = 36\nx_1 = -7"))
    fake_llm.scores(
        {
            item.text: score(
                1,
                feedback="W kroku 2 pojawia się błąd w obliczeniu pierwiastka.",
                mistake="błąd w obliczeniu x_1",
            )
        }
    )

    result = await grading.result(*await hand_in(bank, [item]))

    assert result is not None
    assert [
        (i.ai_points, i.max_points, i.reading, i.doubt, i.feedback, i.mistake) for i in result.items
    ] == [
        (
            1,
            2,
            "readable",
            False,
            "W kroku 2 pojawia się błąd w obliczeniu pierwiastka.",
            "błąd w obliczeniu x_1",
        )
    ]
    assert not result.held
    assert result.comment == f"Zadanie 1: 1/2 pkt\n\n{AI_LINE}"
    prompt = fake_llm.prompt("grading.score")
    assert all(
        part in prompt
        for part in (
            item.text,
            item.model_solution,
            *(level.description for level in item.rubric),
            "x_1 = -7",
        )
    )


async def test_a_grading_doubt_holds_the_submission_and_names_the_item(bank, fake_llm):
    first, second = open_item(text="Rozwiąż $x - 1 = 0$."), open_item(text="Rozwiąż $x + 2 = 0$.")
    fake_llm.transcribes(read(1, transcription="x = 1"), read(2, transcription="x = 2"))
    fake_llm.scores({first.text: score(2), second.text: score(1, doubt=True, feedback="...")})

    result = await grading.result(*await hand_in(bank, [first, second]))

    assert result is not None
    assert [(i.ai_points, i.doubt) for i in result.items] == [(2, False), (1, True)]
    assert [r.model_dump() for r in result.held_reasons] == [
        {"reason": "wątpliwa ocena", "items": [2]}
    ]
    assert result.spot_check


async def test_a_drawing_flags_the_submission_without_holding_it(bank, fake_llm):
    item = open_item()
    fake_llm.transcribes(read(1, transcription="[rysunek trójkąta] h = 4", drawing=True))
    fake_llm.scores({item.text: score(2)})

    result = await grading.result(*await hand_in(bank, [item]))

    assert result is not None
    assert [i.drawing for i in result.items] == [True]
    assert (result.held, result.held_reasons) == (False, [])
    assert result.spot_check
    assert [r.model_dump() for r in result.spot_check_reasons] == [
        {"reason": "rysunek", "items": [1]}
    ]


async def test_a_mixed_submission_scores_only_open_items_with_the_model(bank, fake_llm):
    choice, solved, empty = closed(correct="B"), open_item(points=2), open_item(text="Wykaż...")
    fake_llm.transcribes(
        read(1, chosen="C", transcription="C"),
        read(2, transcription="x_1 = -1, x_2 = 5"),
        read(3, reading="blank"),
    )
    fake_llm.scores({solved.text: score(2, feedback="Ignored for full points.")})

    result = await grading.result(*await hand_in(bank, [choice, solved, empty]))

    assert result is not None
    assert fake_llm.keys == ["grading.transcribe", "grading.verify", "grading.score"]
    assert [(i.ai_points, i.feedback, i.mistake) for i in result.items] == [
        (0, "błędna odpowiedź", None),
        (2, "poprawnie", None),
        (0, "brak rozwiązania", None),
    ]
    assert result.comment == (
        "Zadanie 1: 0/1 pkt – błędna odpowiedź\n"
        "Zadanie 2: 2/2 pkt – poprawnie\n"
        f"Zadanie 3: 0/2 pkt – brak rozwiązania\n\n{AI_LINE}"
    )


async def test_points_outside_the_items_range_are_capped_and_put_in_doubt(bank, fake_llm):
    item = open_item(points=2)
    fake_llm.transcribes(read(1, transcription="x = 5"))
    fake_llm.scores({item.text: score(3)})

    result = await grading.result(*await hand_in(bank, [item]))

    assert result is not None
    assert [(i.ai_points, i.doubt) for i in result.items] == [(2, True)]
    assert result.held


async def test_the_scoring_prompt_sets_the_voice_and_forbids_the_solution(bank, fake_llm):
    item = open_item()
    fake_llm.transcribes(read(1, transcription="x = 5"))
    fake_llm.scores({item.text: score(1, feedback="W kroku 2 pojawia się błąd.")})

    await hand_in(bank, [item])

    prompt = fake_llm.prompt("grading.score")
    assert all(
        rule in prompt
        for rule in (
            "in Polish",
            '"ty"',
            "W kroku 2 pojawia się błąd",
            "Części rozwiązania nie udało",
            "Never reveal the Model solution or the final answer",
        )
    )


async def test_lost_points_without_feedback_are_put_in_doubt(bank, fake_llm):
    item = open_item(points=2)
    fake_llm.transcribes(read(1, transcription="P = 24"))
    fake_llm.scores({item.text: score(1, feedback="")})

    result = await grading.result(*await hand_in(bank, [item]))

    assert result is not None
    assert [(i.ai_points, i.doubt) for i in result.items] == [(1, True)]
    assert result.held


async def test_an_item_missing_from_the_transcription_is_not_judged_wrong(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    result = await grading.result(*await hand_in(bank, [closed(), open_item()]))

    assert result is not None
    assert fake_llm.keys == ["grading.transcribe", "grading.verify"]
    assert [(i.reading, i.ai_points, i.feedback) for i in result.items][1] == (
        "unsure",
        0,
        "nie udało się odczytać rozwiązania",
    )


async def test_pdf_pages_and_heic_photos_reach_the_model_as_page_images(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    await hand_in(bank, [closed()], files=[pdf(pages=2), heic((1200, 1600))])

    # A4 rendered to 2000 px on the long side.
    assert [i.size for i in fake_llm.images()] == [(1414, 2000), (1414, 2000), (1200, 1600)]


async def test_files_that_are_neither_images_nor_pdfs_are_skipped(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    result = await grading.result(
        *await hand_in(bank, [closed()], files=[b"notatki.txt", b"%PDF-1.7 broken", photo()])
    )

    assert result is not None
    assert len(fake_llm.images()) == 1
    assert not result.held


async def test_more_than_six_pages_are_held_and_not_graded(bank, fake_llm):
    # Counted after the PDF is split: 5 + 2 pages.
    result = await grading.result(
        *await hand_in(bank, [closed(), open_item()], files=[pdf(pages=5), photo(), photo()])
    )

    assert result is not None
    assert fake_llm.keys == []
    assert [r.model_dump() for r in result.held_reasons] == [
        {"reason": "za dużo stron", "items": []}
    ]
    assert result.spot_check
    assert (result.items, result.comment) == ([], "")
    assert len(await graded_events(result.submission_id)) == 1


async def test_a_hand_in_with_no_usable_file_is_held_and_not_graded(bank, fake_llm):
    result = await grading.result(*await hand_in(bank, [closed()], files=[b"notatki.txt"]))

    assert result is not None
    assert fake_llm.keys == []
    assert [r.model_dump() for r in result.held_reasons] == [
        {"reason": "brak czytelnych plików", "items": []}
    ]
    assert (result.items, result.comment) == ([], "")


async def test_work_that_fits_no_single_item_makes_that_item_unsure(bank, fake_llm):
    first, second = open_item(text="Rozwiąż $x - 1 = 0$."), open_item(text="Rozwiąż $x + 2 = 0$.")
    fake_llm.transcribes(
        read(1, transcription="x = 1"),
        # Unnumbered work that could belong to either Item.
        read(2, reading="unsure", transcription="x = -2 [bez numeru zadania]"),
    )
    fake_llm.scores({first.text: score(2), second.text: score(2)})

    result = await grading.result(*await hand_in(bank, [first, second]))

    assert result is not None
    assert [(i.reading, i.ai_points) for i in result.items] == [("readable", 2), ("unsure", 2)]
    assert [r.model_dump() for r in result.held_reasons] == [
        {"reason": "niepewny odczyt", "items": [2]}
    ]
    assert "work that fits no single Item" in fake_llm.prompt()


async def test_work_under_a_number_outside_the_assignment_is_ignored(bank, fake_llm):
    item = open_item()
    fake_llm.transcribes(
        read(1, transcription="x_1 = -1, x_2 = 5"),
        read(7, transcription="2 + 2 = 4"),
        read(8, chosen="A", transcription="A"),
    )
    fake_llm.scores({item.text: score(2)})

    result = await grading.result(*await hand_in(bank, [item]))

    assert result is not None
    assert [(i.number, i.ai_points) for i in result.items] == [(1, 2)]
    assert fake_llm.keys == ["grading.transcribe", "grading.verify", "grading.score"]
    assert result.comment == f"Zadanie 1: 2/2 pkt – poprawnie\n\n{AI_LINE}"


async def test_six_pages_are_still_transcribed(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    # PDF allows bytes before its header.
    files = [b"junk from the phone\n" + pdf(pages=4), photo(), photo()]
    result = await grading.result(*await hand_in(bank, [closed()], files=files))

    assert result is not None
    assert len(fake_llm.images()) == 6
    assert not result.held


async def test_a_confirmed_transcription_keeps_its_reading(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    result = await grading.result(*await hand_in(bank, [closed()], files=[photo(), photo()]))

    assert result is not None
    assert fake_llm.keys == ["grading.transcribe", "grading.verify"]
    assert [(i.reading, i.verification_note) for i in result.items] == [("readable", None)]
    assert not result.held
    seen = fake_llm.models["grading.verify"].seen
    assert len(seen) == 1
    assert sum(p["type"] == "image_url" for p in parts(seen[0])) == 2
    assert '"transcription": "B"' in text_of(seen[0])


async def test_a_disputed_item_becomes_unsure_and_holds_with_the_note(bank, fake_llm):
    item = open_item()
    fake_llm.transcribes(
        read(1, chosen="B", transcription="B"), read(2, transcription="x_1 = -1, x_2 = 5")
    )
    fake_llm.verifies(confirmed(1), disputed(2, "x_1: -1 czy -7?"))
    fake_llm.scores({item.text: score(2)})

    result = await grading.result(*await hand_in(bank, [closed(), item]))

    assert result is not None
    assert [(i.reading, i.verification_note) for i in result.items] == [
        ("readable", None),
        ("unsure", "x_1: -1 czy -7?"),
    ]
    assert [r.model_dump() for r in result.held_reasons] == [
        {"reason": "niepewny odczyt", "items": [2]}
    ]


async def test_work_invented_on_an_empty_page_is_disputed(bank, fake_llm):
    # The prototype read an answer "B" out of a bare "Z. 1".
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))
    fake_llm.verifies(disputed(1, "na stronie jest tylko numer Z. 1, bez odpowiedzi"))

    result = await grading.result(*await hand_in(bank, [closed()]))

    assert result is not None
    assert [(i.reading, i.verification_note) for i in result.items] == [
        ("unsure", "na stronie jest tylko numer Z. 1, bez odpowiedzi")
    ]
    assert result.held


async def test_a_redelivered_job_makes_no_second_call_or_event(bank, fake_llm):
    fake_llm.transcribes(read(1, chosen="B", transcription="B"))

    submission_id, handed_in_at = await hand_in(bank, [closed()], deliveries=2)

    assert fake_llm.keys == ["grading.transcribe", "grading.verify"]
    assert len(await graded_events(submission_id)) == 1
    assert await grading.result(submission_id, handed_in_at) is not None


async def test_a_dispute_never_turns_unreadable_work_into_a_guess(bank, fake_llm):
    fake_llm.transcribes(read(1, reading="unreadable", transcription="[nieczytelne]"))
    fake_llm.verifies(disputed(1, "widać x = 3"))

    result = await grading.result(*await hand_in(bank, [open_item()]))

    assert result is not None
    assert fake_llm.keys == ["grading.transcribe", "grading.verify"]
    assert [(i.reading, i.feedback) for i in result.items] == [
        ("unreadable", "nie udało się odczytać rozwiązania")
    ]
    assert [r.reason for r in result.held_reasons] == ["nieczytelne"]


async def test_work_missed_on_a_blank_item_is_held_without_scoring_nothing(bank, fake_llm):
    fake_llm.transcribes(read(1, reading="blank"))
    fake_llm.verifies(disputed(1, "pod Z. 1 jest rozwiązanie"))

    result = await grading.result(*await hand_in(bank, [open_item()]))

    assert result is not None
    assert fake_llm.keys == ["grading.transcribe", "grading.verify"]
    assert [(i.reading, i.ai_points, i.feedback, i.verification_note) for i in result.items] == [
        ("unsure", 0, "nie udało się odczytać rozwiązania", "pod Z. 1 jest rozwiązanie")
    ]
    assert result.held
