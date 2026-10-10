from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from classlop.items import ItemVersion
from classlop.shared import llm

PROMPT = """You score one open Item of a Polish high-school maths test, CKE-style, from the
Transcription of the student's handwritten work. All mathematics is inline LaTeX.

- points: whole points from 0 to the Item's maximum, at the highest Rubric level the work reaches.
  Accept any correct method and any equivalent form, not only the Model solution's.
- doubt: true when the work fits no Rubric level cleanly, e.g. a correct result after a wrong step,
  or a method the Rubric does not foresee. You still give your best points.
- feedback: in Polish, at most two sentences: the first wrong step, the mistake, and one hint.
  Impersonal, addressing the student as "ty", factual and calm; criticise the work, never the
  person; no praise, no exclamation marks, no emoji. For example: "W kroku 2 pojawia się błąd: ...".
  Where the Transcription marks part of the work unreadable, say "Części rozwiązania nie udało
  się odczytać." and never guess what it said.
  Never reveal the Model solution or the final answer, not even in part.
  Required whenever the work loses points, also when it simply stops early: then name the first
  missing step. Empty only at full points; such an Item is marked "poprawnie" for you.
- mistake: the mistake in a few Polish words, so that the same mistake made by different students
  reads alike, e.g. "błędny znak przy przenoszeniu wyrazu". Null when there is no mistake."""


class Score(BaseModel):
    points: int
    doubt: bool
    feedback: str
    mistake: str | None


async def score(item: ItemVersion, transcription: str) -> Score:
    rubric = "\n".join(f"- {level.points} pkt: {level.description}" for level in item.rubric)
    shown = (
        f"Item (maximum {item.points} pkt):\n{item.text}\n\n"
        f"Model solution:\n{item.model_solution}\n\n"
        f"Rubric:\n{rubric}\n\n"
        f"Transcription:\n{transcription}"
    )
    return await llm.ask("grading.score", Score, [SystemMessage(PROMPT), HumanMessage(shown)])
