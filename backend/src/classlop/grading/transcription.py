import base64
import json

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from classlop.grading.models import Reading
from classlop.items import ItemVersion
from classlop.shared import llm

PROMPT = """You read photos of a Polish high-school student's handwritten maths work for the Items
of one Assignment. There may be several pages. Work may be unnumbered or out of order: work without
an Item number belongs to the Item whose task it copies. Ignore work labelled with a number that is
not one of the Items.

For each Item report:
- transcription: verbatim LaTeX of what the student wrote for that Item, mistakes included, never
  corrected or completed. Describe drawings, crossed-out parts and parts you cannot read in square
  brackets, in Polish. For a closed Item, give only the chosen option label.
  Transcribe nothing where nothing is written: an Item number such as "Z. 1" with no work after it
  is blank, its transcription is empty, and you never guess what the student might have meant.
- reading: "readable" when you are sure what is written; "unsure" when you are not (1 or 7, two
  options marked, work that fits no single Item); "unreadable" when work is there but cannot be
  read; "blank" when nothing is written for the Item.
- drawing: true if the work contains a drawing.
- chosen_option: for a closed Item, the label of the option the student chose. If the student wrote
  an option's value instead of its label, give the label of the one option with that value. If no
  option is chosen, two options are marked, or a crossing-out leaves the choice unclear, give null
  and reading "unsure". Report the student's choice, never which option is correct. Null for open
  Items and blank Items."""


class ItemTranscription(BaseModel):
    number: int
    transcription: str
    reading: Reading
    drawing: bool
    chosen_option: str | None


class Transcript(BaseModel):
    items: list[ItemTranscription]


def _shown(number: int, item: ItemVersion) -> dict:
    # The key (correct_options) never reaches the model.
    shown = {"number": number, "format": item.item_format, "text": item.text}
    if item.item_format == "closed":
        shown["options"] = item.options
    return shown


async def transcribe(
    items: list[tuple[int, ItemVersion]], pages: list[bytes]
) -> dict[int, ItemTranscription]:
    """One call over all pages; the Transcription per Item number."""
    shown = json.dumps([_shown(n, i) for n, i in items], ensure_ascii=False, indent=1)
    images = [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(p).decode()},
        }
        for p in pages
    ]
    transcript = await llm.ask(
        "grading.transcribe",
        Transcript,
        [
            SystemMessage(PROMPT),
            HumanMessage([{"type": "text", "text": "Items:\n" + shown}, *images]),
        ],
    )
    return {t.number: t for t in transcript.items}
