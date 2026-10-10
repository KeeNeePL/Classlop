"""The grading evaluation: every Submission of an evaluation set graded with the real models,
compared with its expected result, and recorded as a LangSmith experiment. See
`evals/grading/README.md`."""

import asyncio
import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from classlop import items
from classlop.grading.handlers import grade
from classlop.grading.result import result
from classlop.items import CurriculumTopic, ItemVersion, RubricLevel
from classlop.shared import storage
from classlop.shared.migrate import migrate
from classlop.shared.models import Job
from classlop.shared.queue import MAX_RECEIVES
from classlop.shared.settings import get_settings

SETS = Path(__file__).parents[3] / "evals" / "grading"
CONCURRENCY = 4


def metrics(outputs: list[dict], references: list[dict]) -> dict:
    """Points and reading-state agreement per Item, Held recall and precision, and the Feedback
    and summaries that give away an Item's final answer or Model solution."""
    pairs = [
        (next((i for i in out["items"] if i["number"] == ref["number"]), None), ref)
        for out, expected in zip(outputs, references, strict=True)
        for ref in expected["items"]
    ]

    def agreement(field: str, item_format: str | None = None) -> float | None:
        compared = [
            got is not None and got[field] == ref[field]
            for got, ref in pairs
            if item_format in (None, ref["format"])
        ]
        return sum(compared) / len(compared) if compared else None

    held = [(out["held"], ref["held"]) for out, ref in zip(outputs, references, strict=True)]
    held_correctly = sum(got and expected for got, expected in held)
    expected_held, got_held = sum(e for _, e in held), sum(g for g, _ in held)
    leaks = [_gives_away(item["feedback"], ref["leaks"]) for item, ref in pairs if item is not None]
    every_leak = [
        leak for expected in references for ref in expected["items"] for leak in ref["leaks"]
    ]
    return {
        "submissions": len(outputs),
        "items": len(pairs),
        "held_expected": expected_held,
        "held_graded": got_held,
        "points_agreement": agreement("points"),
        "points_agreement_closed": agreement("points", "closed"),
        "points_agreement_open": agreement("points", "open"),
        "reading_agreement": agreement("reading"),
        "held_recall": held_correctly / expected_held if expected_held else None,
        "held_precision": held_correctly / got_held if got_held else None,
        "feedback_leaks": sum(leaks),
        "summary_leaks": sum(_gives_away(out["summary"], every_leak) for out in outputs),
    }


def _gives_away(text: str, leaks: list[str]) -> bool:
    # Whole numbers only: "x=5" is not given away by "x=50" or "x=5,5", but is by "x=5.".
    number_goes_on = r"\d|[.,]\d"
    return any(
        re.search(
            rf"(?<![\d.,]){re.escape(_normalised(leak))}(?!{number_goes_on})", _normalised(text)
        )
        for leak in leaks
    )


def _normalised(latex: str) -> str:
    """Spacing, dollars and fraction styles left out, so the same maths matches however typed."""
    text = re.sub(r"\\[dt]frac", r"\\frac", latex)
    return re.sub(r"\s|\$|\\left|\\right", "", text)


def _version(item: dict) -> ItemVersion:
    closed = item["format"] == "closed"
    return ItemVersion(
        id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        number=item["number"],
        created_at=datetime.now(UTC),
        item_format=item["format"],
        text=item["text"],
        points=item["max_points"],
        options=item["options"] or {},
        correct_options=[item["answer"]] if closed else [],
        answer=None if closed else item["answer"],
        model_solution=item["model_solution"],
        rubric=[RubricLevel(**level) for level in item["rubric"] or []],
        curriculum_topics=[CurriculumTopic(**t) for t in item["curriculum_topics"]],
        difficulty=item["difficulty"],
        general_requirements=item["general_requirements"],
    )


def load(set_dir: Path) -> tuple[list[ItemVersion], dict[str, dict]]:
    """The set's Items, and per Submission its files and reference: the expected result, with
    each Item's format and leaks from `items.json`."""
    spec = json.loads((set_dir / "items.json").read_text(encoding="utf-8"))["items"]
    versions = [_version(i) for i in spec]
    by_number = {i["number"]: i for i in spec}
    submissions = {}
    for folder in sorted((set_dir / "submissions").iterdir()):
        expected = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
        reference = {
            "held": expected["held"],
            "items": [
                {
                    **{k: i[k] for k in ("number", "points", "reading")},
                    "format": by_number[i["number"]]["format"],
                    "leaks": by_number[i["number"]].get("leaks", []),
                }
                for i in expected["items"]
            ],
        }
        files = sorted(p for p in folder.iterdir() if p.name != "expected.json")
        submissions[folder.name] = {"files": files, "reference": reference}
    return versions, submissions


async def grade_submission(versions: list[ItemVersion], files: list[Path]) -> dict:
    """Grade one Submission as `teams` would hand it in, and read back what grading made."""
    submission_id, handed_in_at = uuid.uuid4(), datetime.now(UTC)
    keys = [f"grading/evaluation/{submission_id}/file-{n}" for n in range(1, len(files) + 1)]
    for key, file in zip(keys, files, strict=True):
        await asyncio.to_thread(storage.put, key, file.read_bytes(), "application/octet-stream")
    payload = {
        "submission_id": str(submission_id),
        "handed_in_at": handed_in_at.isoformat(),
        "items": [{"id": str(v.id), "number": n} for n, v in enumerate(versions, 1)],
        "files": keys,
        "assignment_id": str(uuid.uuid4()),
        "due_at": (handed_in_at + timedelta(days=1)).isoformat(),
    }

    async def progress(value: dict) -> None:
        pass

    # As the last attempt: a run that fails is stored Held with no Items, as in production,
    # and counts as disagreeing instead of ending the whole evaluation.
    job = Job(id=uuid.uuid4(), kind="grading.grade", payload=payload, attempts=MAX_RECEIVES)
    await grade(job, progress)
    graded = await result(submission_id, handed_in_at)
    assert graded is not None
    return {
        "held": graded.held,
        "summary": graded.summary,
        "items": [
            {"number": i.number, "points": i.points, "reading": i.reading, "feedback": i.feedback}
            for i in graded.items
        ],
    }


async def evaluate(set_name: str) -> dict:
    set_dir = SETS / set_name
    versions, submissions = load(set_dir)
    by_id = {v.id: v for v in versions}

    async def get_versions(ids: list[uuid.UUID]) -> list[ItemVersion]:
        return [by_id[i] for i in ids]

    # The set's Items are not in the Item bank; the set brings its own.
    items.get_versions = get_versions
    await asyncio.to_thread(migrate)
    slots = asyncio.Semaphore(CONCURRENCY)

    async def target(inputs: dict) -> dict:
        async with slots:
            return await grade_submission(versions, submissions[inputs["submission"]]["files"])

    settings = get_settings()
    if not settings.langsmith_api_key:
        print("LANGSMITH_API_KEY is not set: grading locally, no experiment is recorded.")
        names = list(submissions)
        outputs = await asyncio.gather(*(target({"submission": n}) for n in names))
        return metrics(list(outputs), [submissions[n]["reference"] for n in names])
    from langsmith import Client

    client = Client(
        api_url=settings.langsmith_endpoint,
        api_key=settings.langsmith_api_key.get_secret_value(),
    )
    return await _experiment(client, set_dir, submissions, target)


async def _experiment(client, set_dir: Path, submissions: dict, target) -> dict:
    from langsmith import aevaluate

    settings = get_settings()
    # A new dataset whenever the set changes, so experiments on one dataset stay comparable.
    digest = hashlib.sha256()
    for path in sorted(set_dir.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(set_dir).as_posix().encode() + path.read_bytes())
    dataset = f"grading-{set_dir.name}-{digest.hexdigest()[:8]}"
    if not client.has_dataset(dataset_name=dataset):
        client.create_dataset(dataset, description=f"Grading evaluation {set_dir.name}")
    # Also fills a dataset whose examples failed to upload on an earlier run.
    if not any(client.list_examples(dataset_name=dataset, limit=1)):
        client.create_examples(
            dataset_name=dataset,
            examples=[
                {"inputs": {"submission": name}, "outputs": s["reference"]}
                for name, s in submissions.items()
            ],
        )

    def per_submission(outputs: dict, reference_outputs: dict) -> dict:
        return _as_feedback(metrics([outputs], [reference_outputs]))

    def whole_set(outputs: list[dict], reference_outputs: list[dict]) -> dict:
        return _as_feedback(metrics(outputs, reference_outputs))

    results = await aevaluate(
        target,
        data=dataset,
        evaluators=[per_submission],
        # Read by argument name, which the typed signature cannot express.
        summary_evaluators=[whole_set],  # type: ignore[list-item]
        experiment_prefix=f"grading-{set_dir.name}",
        metadata={"models": settings.llm_models, "default_model": settings.llm_chat_model},
        max_concurrency=CONCURRENCY,
        client=client,
    )
    rows = [row async for row in results]
    print(f"LangSmith experiment: {results.experiment_name}")
    return metrics(
        [row["run"].outputs or {} for row in rows],
        [row["example"].outputs or {} for row in rows],
    )


def _as_feedback(report: dict) -> dict:
    """The report in the shape LangSmith records as feedback scores."""
    return {"results": [{"key": k, "score": v} for k, v in report.items()]}


def print_report(set_name: str, report: dict) -> None:
    print(f"\nGrading evaluation, {set_name}")
    for key, value in report.items():
        shown = "n/a" if value is None else f"{value:.0%}" if isinstance(value, float) else value
        print(f"  {key:<24} {shown}")
