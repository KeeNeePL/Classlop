import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from classlop.grading.pages import image_parts
from classlop.grading.transcription import ItemTranscription, item_for_model
from classlop.items import ItemVersion
from classlop.shared import llm

PROMPT = """You check a first Transcription of a Polish high-school student's handwritten maths work
against the photos of the pages. For each Item you get the first Transcription (LaTeX), its
reading state and, for a closed Item, its options and the chosen option. Compare it with what is
actually written on the pages for that Item. Do not judge whether the maths is correct: mistakes
stay as written.

- A closed Item's Transcription is only the chosen label. The student may have written the
  option's value instead of its label ("1" for the option whose value is $1$); that is the same
  choice.
- An Item number or label with no work after it ("Z. 1", "2.1") is a blank Item, not work.
  A blank Transcription of such an Item, or of an Item with nothing written, is confirmed.
  A remark that is not a solution ("nie wiem") is not work either.
- Drawings, crossed-out and unreadable parts are described in square brackets; the description
  need not match word for word, only what it describes.

For each Item report:
- verdict: "confirmed" when the Transcription matches what is written, symbol by symbol.
  "disputed" when any part differs or could be read another way (1 or 7, a sign, an exponent,
  a crossed-out part), when the Transcription holds work that is not on the page (such as an
  answer read out of a bare "Z. 1"), when work on the page is missing from it, when a blank Item
  has work written for it, or when the chosen option is not the one the student marked or wrote.
- note: for a dispute, a short Polish phrase naming the disputed part, e.g. "x_1: -1 czy -7?".
  Empty when confirmed."""


class ItemCheck(BaseModel):
    number: int
    verdict: Literal["confirmed", "disputed"]
    note: str


class Verification(BaseModel):
    items: list[ItemCheck]


async def verify(
    items: list[tuple[int, ItemVersion]],
    pages: list[bytes],
    transcriptions: dict[int, ItemTranscription],
) -> dict[int, ItemCheck]:
    """One call over all pages and the first Transcription; the check per Item number."""
    shown = [
        item_for_model(n, item)
        | {"reading": t.reading, "transcription": t.transcription, "chosen_option": t.chosen_option}
        for n, item in items
        if (t := transcriptions.get(n))
    ]
    text = "Transcription:\n" + json.dumps(shown, ensure_ascii=False, indent=1)
    verification = await llm.ask(
        "grading.verify",
        Verification,
        [
            SystemMessage(PROMPT),
            HumanMessage([{"type": "text", "text": text}, *image_parts(pages)]),
        ],
    )
    return {c.number: c for c in verification.items}
