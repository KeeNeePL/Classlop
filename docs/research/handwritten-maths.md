# Can AI read handwritten maths

Research for [#6](https://github.com/KeeNeePL/Classlop/issues/6). Researched 2026-10-08 for the grading area. Prices and model names change often; re-check the linked pages before quoting them.

## Answer

Yes, well enough for AI-graded Submissions with a teacher Spot-check, not well enough to skip the Spot-check.

- On short, objective answers, current models agree with human graders 89-99% of the time per rubric item ([Levine et al. 2026](https://arxiv.org/abs/2605.19043)).
- On multi-step solutions scored against a rubric, they are still clearly worse than a human grader, especially on geometry ([CHECK-MAT](https://arxiv.org/abs/2507.22958), [Perš et al. 2026](https://arxiv.org/abs/2601.00730)).
- Most errors come from **reading** the handwriting, not from applying the rubric. In the 2026 head-to-head, 87% of the best model's errors were transcription failures ([Levine et al. 2026](https://arxiv.org/abs/2605.19043)). Image quality and pipeline design therefore matter more than the choice of model.
- Cost is not a constraint. A single grading pass costs roughly USD 0.02-0.13 per two-page Submission, about USD 10-65 a month for 500 Submissions, and half that through batch APIs (see [Cost](#cost)).

**Recommendation for the grading area.** Build the grader provider-agnostic in LangChain and make the pipeline do the work:

1. Per Item, first transcribe verbatim, then grade against the model solution and rubric.
2. Always supply the model solution.
3. Return structured output with a confidence or illegibility flag.
4. Route flagged Submissions to the Spot-check queue first.

Start with a Gemini Flash-tier model (`gemini-3.8-flash`). It led the 2026 head-to-head on rubric items and is cheap. Elsewhere, Gemini models led or tied in most studies here, though not in CHECK-MAT. On day one, run a small bake-off against `claude-sonnet-5-5` and `gpt-6.1-sol` on invented handwritten Submissions. No public 2026 benchmark covers current Claude or GPT-6 models on this task.

## Evidence: how reliable

The newest studies come first. All of them use university or foreign school material. None covers Polish school mathematics, so treat the numbers as indicative.

| Study | Material | Models | Result |
|---|---|---|---|
| [Levine et al., May 2026](https://arxiv.org/abs/2605.19043) ([full text](https://arxiv.org/html/2605.19043)) | ~600 photographed handwritten answers, 2 US university STEM courses, rubric items | GPT-5-mini, GPT-5.1, Gemini-3-flash | Rubric-item accuracy per question: Gemini-3-flash 89-99%, GPT-5-mini 89-98%, GPT-5.1 87-95%. Transcription caused 70-100% of disagreements in 14 of 15 model-question pairs. |
| [Perš et al., Jan 2026](https://arxiv.org/abs/2601.00730) ([full text](https://arxiv.org/html/2601.00730)) | Scanned A4 engineering quizzes in **Slovenian**, the closest language evidence to Polish | GPT-5.2, Gemini-3 Pro | Mean absolute difference from the lecturer of about 8 percentage points, with low bias. About 17% of exams would trigger manual review. Pipeline: reference solution plus rules, 3 independent graders, a supervisor model. Removing the reference solution raised the error and caused systematic over-grading (bias +6 to +8 points). |
| [Grabowski, Jun 2026](https://arxiv.org/abs/2606.11477) | 61 exams, 3,141 handwritten single-letter answers | VLMs, unnamed | 98.4% accuracy. Putting the reference solution in the prompt cut false negatives to 0.58%. |
| [EDU-CIRCUIT-HW, Jan 2026](https://arxiv.org/abs/2602.00095) | 1,300+ real university STEM solutions | Several, GPT-5.1 as grader | Reports large "latent" recognition failures that downstream grades hide. Routing 3.3% of Submissions to humans made the system robust. |
| [ScratchMath, Mar 2026](https://arxiv.org/abs/2603.24961) | 1,720 Chinese primary and middle school scratchwork samples | 16 models, best o4-mini | Diagnosing *why* a Student erred is far below human level. Error-cause classification: 40-47% for the best model, 78-82% for humans. |
| [Henkel et al., Oct 2025](https://arxiv.org/abs/2510.05538) | 288 handwritten arithmetic answers (Ghana, middle school), and 150 Student drawings | Claude 3.5 Sonnet, Claude 3.7, Gemini 2.5 Pro, GPT-4.1 | Arithmetic: Gemini 2.5 Pro reached 95% grading accuracy (kappa 0.90), Claude 3.7 84%, GPT-4.1 79%. Claude accepted wrong answers as correct in 14-21% of cases, Gemini in 4%. Grading drawings directly reached only kappa 0.20. |
| [CHECK-MAT, Jul 2025](https://arxiv.org/abs/2507.22958) | 122 scanned Russian national exam (EGE) solutions, official rubric | 7 models, best o4-mini | Exact rubric score only 56.6% of the time, average distance 0.6 points. Geometry was the weakest. |
| [FERMAT, ACL 2025](https://arxiv.org/abs/2501.07244) | 2,200+ handwritten grade 7-12 solutions with planted errors | 9 models | Best error correction 77% (Gemini 1.5 Pro). Accuracy rose when handwriting was replaced by printed text. |

How to read this for Classlop:

- **Closed Items** (a number, an answer letter, a single expression) are close to solved: 95-99% agreement when the answer is legible.
- **Open, multi-step Items with partial credit** are workable but noisy. Expect a few points of drift per Submission and roughly 1 in 6 Submissions worth a human look ([Perš et al.](https://arxiv.org/html/2601.00730)).
- **Geometry sketches** and other drawings are the weak spot ([CHECK-MAT](https://arxiv.org/abs/2507.22958), [Henkel et al.](https://arxiv.org/abs/2510.05538)). Grade the written reasoning and the result, not the drawing itself, or route these Items to Spot-check.
- **Feedback on why a Student went wrong** is the least reliable output ([ScratchMath](https://arxiv.org/abs/2603.24961)). Phrase it cautiously.

## Failure modes

1. **Misreading the handwriting.** This is the dominant error ([Levine et al.](https://arxiv.org/html/2605.19043), [CHECK-MAT](https://arxiv.org/abs/2507.22958), [ScratchMath](https://arxiv.org/abs/2603.24961)). Typical confusions in maths are 1/7, 5/S, x/×, minus signs and fraction bars, and exponents.
2. **Over-correction.** The model silently "fixes" the Student's mistake while transcribing, which hides exactly what should lose points ([Seong et al. 2026](https://arxiv.org/abs/2604.22774)). Mitigation: instruct a verbatim transcription and grade that transcription.
3. **Hallucinated content.** The model invents work in blank or blurry regions ([Levine et al.](https://arxiv.org/html/2605.19043), [Perš et al.](https://arxiv.org/html/2601.00730)). Mitigation: run a presence check per Item before grading.
4. **Leniency without a reference.** Without a model solution, models over-grade systematically ([Perš et al.](https://arxiv.org/html/2601.00730), [Grabowski](https://arxiv.org/abs/2606.11477)). Older Claude models were notably lenient on wrong answers ([Henkel et al.](https://arxiv.org/abs/2510.05538)).
5. **Rejecting equivalent forms or alternative methods.** Examples include an unsimplified fraction, a negated vector, or a method different from the model solution ([Levine et al.](https://arxiv.org/html/2605.19043), [CHECK-MAT](https://arxiv.org/abs/2507.22958)). Mitigation: the rubric states which forms are accepted.
6. **Penalising a flawed intermediate step when the final answer is right**, or the reverse, inconsistently ([Henkel et al.](https://arxiv.org/abs/2510.05538)).
7. **Misjudging severity on partial-credit rubrics**, and occasionally producing no score at all ([CHECK-MAT](https://arxiv.org/abs/2507.22958)). Mitigation: use structured output and validate it.
8. **Rotated or skewed photos** degrade reading. All three providers document this ([Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision#limitations), [OpenAI vision](https://developers.openai.com/api/docs/guides/images-vision), [Levine et al.](https://arxiv.org/html/2605.19043)).
9. **No usable confidence signal yet.** Disagreement between models did not reliably predict wrong grades in [Levine et al.](https://arxiv.org/html/2605.19043). Spot-check sampling should therefore stay partly random, not rely only on flags.

## Image requirements

| | Claude | Gemini | OpenAI |
|---|---|---|---|
| Formats | JPEG, PNG, GIF, WebP. **No HEIC** | PNG, JPEG, WebP, HEIC, HEIF | PNG, JPEG, WebP, GIF |
| Native resolution | Claude 4.7 and later: long edge up to 2576 px, max 4,784 visual tokens (28x28 px patches). Larger images are downscaled. | Set by `media_resolution`: 280 / 560 / 1120 (default) / 2240 tokens per image. Use `high` for fine text. | `detail: high`: 2,500 patches of 32 px, e.g. 2048x2048 is resized to 1600x1600. `original` for dense text. |
| Per-image limit | 10 MB, max 8000x8000 px. Above 20 images per request, each must be 2000 px or less. | 20 MB inline request total, or the File API | 512 MB request, 30,000 patches |
| Source | [Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision) | [Gemini image understanding](https://ai.google.dev/gemini-api/docs/image-understanding), [media resolution](https://ai.google.dev/gemini-api/docs/media-resolution) | [OpenAI images and vision](https://developers.openai.com/api/docs/guides/images-vision) |

Practical capture rules. These are drawn from the provider guidance and failure modes above, and the exact thresholds are our judgement, not a source:

- **One page per image**, upright, cropped to the paper, with even light and no shadow across the writing. Auto-rotate from EXIF before sending.
- **Convert HEIC to JPEG** (iPhone default) before sending to Claude or OpenAI.
- **Downscale to the model's native size** yourself, for example a long edge of about 2,500 px for Claude, so you control the result. Avoid heavy or repeated JPEG compression ([Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision#image-quality-guidance)).
- **Scans at 200-300 dpi**, or a phone scanner app such as Microsoft Lens or the Teams/OneDrive scan, beat free-hand photos. Webcams and document cameras produced the blurriest inputs in [Levine et al.](https://arxiv.org/html/2605.19043).
- **Ask Students to write each Item in a marked area** and to cross out cleanly. Answers outside the expected place and crossed-out work were classic failures ([Grabowski](https://arxiv.org/abs/2606.11477), [Henkel et al.](https://arxiv.org/abs/2510.05538)).
- **Show the Student the transcription before final submission**, if Teams makes this possible. [Levine et al.](https://arxiv.org/html/2605.19043) recommend a preview transcription.

## Cost

Assumptions for one Submission: 2 photographed pages, about 3,000 tokens of prompt (instructions, Items, model solution, rubric), and about 4,000 output tokens (transcription, per-Item scores, short feedback, model thinking). Image tokens per page come from each provider's documented maximum: Claude 4,784, Gemini 1,120 at `high`, OpenAI about 3,000 at `high`. Prices are standard-tier USD per million tokens as listed on 2026-10-08.

| Model | Input / output per MTok | Per Submission | 500 Submissions / month | With batch (-50%) |
|---|---|---|---|---|
| Gemini 3.8 Flash (`gemini-3.8-flash`) | $0.75 / $3.75 until 2026-12-31, then $1.50 / $7.50 | ~$0.019 | ~$10 (from 2027: ~$20) | ~$5 |
| Claude Haiku 5.5 (`claude-haiku-5-5`) | $0.10 / $0.50 | ~$0.003 | ~$2 | ~$1 |
| Claude Sonnet 5.5 (`claude-sonnet-5-5`) | $2 / $10 | ~$0.065 | ~$33 | ~$16 |
| Gemini 3.1 Pro Preview (`gemini-3.1-pro-preview`) | $2 / $12 | ~$0.058 | ~$29 | ~$15 |
| OpenAI gpt-6.1-sol | $2 / $10 | ~$0.058 | ~$29 | ~$15 |
| Claude Opus 5.5 (`claude-opus-5-5`) | $4 / $20 | ~$0.13 | ~$65 | ~$33 |

Sources: [Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Claude models](https://platform.claude.com/docs/en/about-claude/models/overview), [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [OpenAI pricing](https://developers.openai.com/api/docs/pricing).

- A 3-grader ensemble with a supervisor, as in [Perš et al.](https://arxiv.org/html/2601.00730), multiplies these figures by about 4.
- Prompt caching of the shared rubric and model solution lowers input cost further when one Assignment's Submissions are graded together.
- Grading is not time-critical, so the batch APIs (50% off at Anthropic, Google and OpenAI) fit naturally.
- Even the most expensive single-pass option stays under USD 70 a month at this volume. A cheap model's savings are worth less than its extra Spot-check work.
- Haiku 5.5 is very cheap, but no benchmark evidence on handwriting was found for it. Include it in the bake-off before relying on it.

## LangChain reachability

All three providers are first-class LangChain integrations: `langchain-anthropic` (`ChatAnthropic`), `langchain-google-genai` (`ChatGoogleGenerativeAI`) and `langchain-openai` (`ChatOpenAI`). They accept the same LangChain v1 image content block ([LangChain messages](https://docs.langchain.com/oss/python/langchain/messages), [Google GenAI integration](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai)):

```python
{"type": "image", "base64": data, "mime_type": "image/jpeg"}  # or "url" / "file_id"
```

This makes the bake-off a model-name change. Two provider-specific settings may need passing through as provider kwargs, and we did not confirm either in the LangChain docs: Gemini's `media_resolution` and OpenAI's `detail`. Claude is also sold through Microsoft Foundry, billed via Azure ([Claude pricing](https://platform.claude.com/docs/en/about-claude/pricing#claude-in-microsoft-foundry-pricing)), which may suit a school already on Microsoft 365.

## Suggested pipeline shape

This sketch is not a decision. It encodes the mitigations above as a LangGraph flow per Submission:

1. **Prepare.** Auto-rotate, convert to JPEG, downscale, one image per page.
2. **Transcribe.** For each Item: a verbatim LaTeX transcription with `[illegible]` markers and an `answer_present` flag. Do not correct anything.
3. **Grade.** Input: transcription, page images, Item, model solution, rubric with accepted equivalent forms. Output: a structured score per rubric point, a short reason, and a confidence value.
4. **Route.** Send these to the Spot-check queue first: illegible or missing answers, low confidence, geometry or drawing Items, and a random sample of the rest.

## Open for the grading area owner

- **Personal data.** Photos of minors' work are personal data under GDPR. Which provider and region is acceptable is part of the Phase 2 LLM provider decision, not this ticket.
- **Bake-off material.** Collect about 20 invented handwritten Submissions (team members' own handwriting, invented Items) to compare the models on day one. Real Student work stays out of the repo.
