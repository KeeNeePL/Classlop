# Grading evaluation set

Invented Items and handwritten Submissions written by the team, never student work or ZPE/CKE content. The evaluation run grades every Submission and compares the result with its `expected.json`.

```
<set>/
├── items.json                 # the Items of one Assignment, in order
└── submissions/<name>/
    ├── page-1.jpg ...         # the hand-in, as photographed (also .pdf or .heic)
    └── expected.json
```

**`items.json`**: per Item `number`, `format` (`closed` or `open`), `max_points`, `text` (inline LaTeX), `options` and `answer` (the correct option label for a closed Item, the final answer in LaTeX for an open one), `model_solution`, `rubric` (ordered levels of `points` and `description`, `null` for closed Items), `curriculum_topics` (a lo2024 `id` and the Polish `name`), `difficulty` and `general_requirements`, as the `items` area's Item versions carry them. Open Items also list `leaks`: LaTeX fragments of the final answer or the Model solution that Feedback must never contain. They are compared without spaces, dollars or `\left`/`\right`, with `\dfrac` and `\tfrac` read as `\frac`.

**`expected.json`**:
- `notes`: what the Submission tests.
- `held`: whether it should be Held.
- `spot_check`: the flag reasons, empty when not flagged: `nieczytelne` (an unreadable Item), `niepewny odczyt` (an unsure Item), `wątpliwa ocena` (an Item in doubt), `rysunek` (a drawing). The first three also hold the Submission.
- `items`: per Item `number`, `reading` (`readable`, `unsure`, `unreadable` or `blank`), `doubt` (`true` when the work fits no Rubric level cleanly; omitted when false), `points` and the verbatim `transcription` in LaTeX. A drawing, a crossed-out part or an unreadable part is described in square brackets. A closed Item's transcription is just the chosen label, also when the Student wrote an option's value instead (it counts as that label when it matches exactly one option), and a blank Item's is empty. Work without an Item number belongs to the Item whose task it copies; only work that fits no single Item is `unsure`.

Strip location data from photos before committing them.

## Running it

By hand, never in CI. It grades with the real models from config and costs real calls.

```sh
docker compose up -d postgres elasticmq s3
cd backend
uv run classlop eval-grading set-01
```

- **The report:**
  - points agreement per Item, overall and for closed and open Items;
  - reading-state agreement;
  - Held recall and precision;
  - the Feedback and summaries that contain a leak.
- **LangSmith:** with `LANGSMITH_API_KEY` set, the run is a LangSmith experiment (EU) on the dataset `grading-<set>-<hash>`. The hash changes when the set does, so experiments on one dataset compare like with like.
- **Without the key:** it grades locally and prints the report only.
- **Side effects:** the run writes results to the dev database, uploads the files under `grading/evaluation/`, and enqueues the events grading always sends. Leave the dev worker stopped while it runs: `teams` does not handle `teams.submission_graded` yet, so those jobs would retry and end in the dead-letter queue.
- **A Submission that fails to grade:** it is stored Held with no Items, as on a last attempt, and counts as disagreeing. It does not stop the run.
