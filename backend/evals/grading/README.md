# Grading evaluation set

Invented Items and handwritten Submissions written by the team, never student work or ZPE/CKE content. The evaluation run grades every Submission and compares the result with its `expected.json`.

```
<set>/
├── items.json                 # the Items of one Assignment, in order
└── submissions/<name>/
    ├── page-1.jpg ...         # the hand-in, as photographed (also .pdf or .heic)
    └── expected.json
```

**`items.json`**: per Item `number`, `format` (`closed` or `open`), `max_points`, `text` (inline LaTeX), `options` and `answer` (the correct option label) for closed Items, `model_solution`, `rubric` (ordered levels of `points` and `description`, `null` for closed Items) and `curriculum_topics` (`id` from the lo2024 set once it exists, and the Polish `name`).

**`expected.json`**:
- `notes`: what the Submission tests.
- `held`: whether it should be Held.
- `spot_check`: the flag reasons, empty when not flagged (`nieczytelne` for a Held Submission, `rysunek` for a drawing).
- `items`: per Item `number`, `reading` (`readable`, `unsure`, `unreadable` or `blank`), `points` and the verbatim `transcription` in LaTeX. A drawing, a crossed-out part or an unreadable part is described in square brackets. A closed Item's transcription is just the chosen label, and a blank Item's is empty.

Strip location data from photos before committing them.
