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
- `spot_check`: the flag reasons, empty when not flagged: `nieczytelne` (an unreadable Item), `niepewny odczyt` (an unsure Item), `wątpliwa ocena` (an Item in doubt), `rysunek` (a drawing). The first three also hold the Submission.
- `items`: per Item `number`, `reading` (`readable`, `unsure`, `unreadable` or `blank`), `doubt` (`true` when the work fits no Rubric level cleanly; omitted when false), `points` and the verbatim `transcription` in LaTeX. A drawing, a crossed-out part or an unreadable part is described in square brackets. A closed Item's transcription is just the chosen label, also when the Student wrote an option's value instead (it counts as that label when it matches exactly one option), and a blank Item's is empty. Work without an Item number belongs to the Item whose task it copies; only work that fits no single Item is `unsure`.

Strip location data from photos before committing them.
