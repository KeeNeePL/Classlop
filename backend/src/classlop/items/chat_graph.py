"""The Chat graph: one thread per Chat in a PostgresSaver, one run per Teacher message. A message
with a file starts an Item upload; any other is read by the model, which asks, starts a
Generation request, writes a new version of one of the Chat's Items or retires one. Graph state
holds the conversation only; Items and messages are records of `items`."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal, Self, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, ValidationError, model_validator

from classlop.items import chat, records, tagging
from classlop.items.curriculum import curriculum
from classlop.items.generation import (
    Draft,
    GenerationOrigin,
    GenerationSpec,
    request_generation,
)
from classlop.items.types import ItemContent
from classlop.items.upload import request_upload
from classlop.shared import llm
from classlop.shared.settings import get_settings

CHAT = """Jesteś Classlop AI, asystentem nauczyciela matematyki w liceum (poziom podstawowy).
Rozmawiasz po polsku, zwięźle. Nauczyciel pisze do Ciebie w czacie; zadania tego czatu są
ponumerowane (lista niżej). Wybierz jedno działanie:
- ask: prośba o nowe zadania nie podaje jeszcze wszystkiego. Potrzebujesz: z czego (temat),
  ile zadań, jaki poziom trudności (easy, medium, hard) i jaki format (closed, open). Zapytaj o to,
  czego brakuje. Niczego nie zakładaj i nie dobieraj wartości domyślnych. To, co nauczyciel już
  powiedział w tym czacie, możesz powtórzyć ("dorzuć 3" po prośbie o łatwe zadania zamknięte).
  Używaj też, gdy wiadomość jest zwykłym pytaniem.
- generate: prośba jest jasna. Nie pytaj o potwierdzenie, zacznij od razu: wypełnij spec (linia
  na każdy rodzaj zadań; curriculum_topics to id z listy tematów) i w reply powiedz, co
  generujesz. Dorzucenie zadań to nowa prośba o generowanie.
- revise: nauczyciel chce zmienić jedno zadanie ("zrób trzecie łatwiejsze"). Podaj number
  zadania z listy i instruction, czyli co zmienić.
- retire: nauczyciel chce wyrzucić jedno zadanie ("wyrzuć piąte"). Podaj number.
W reply zawsze napisz krótką odpowiedź dla nauczyciela.

Zadania tego czatu:
{items}

Tematy podstawy programowej (id: nazwa):
{topics}"""
REVISE = """Jesteś autorem zadań z matematyki dla liceum (poziom podstawowy). Przepisz podane
zadanie tak, jak chce nauczyciel (polecenie), zachowując format i resztę zadania, o ile polecenie
tego nie zmienia. Cała matematyka to LaTeX w znakach $. Zadanie zamknięte: options (A-D) i
correct_options, bez answer, rubric. Zadanie otwarte: answer, model_solution i rubric jako
poziomy punktacji CKE rosnące do points, bez options."""
LISTED_TEXT = 120


class Turn(BaseModel):
    """What the model decides for one message: the reply, and at most one action."""

    action: Literal["ask", "generate", "revise", "retire"]
    reply: str
    spec: GenerationSpec | None = None
    number: int | None = None
    instruction: str | None = None

    @model_validator(mode="after")
    def _has_what_it_acts_on(self) -> Self:
        needs = {
            "generate": self.spec is not None,
            "revise": self.number is not None and bool(self.instruction),
            "retire": self.number is not None,
        }
        if not needs.get(self.action, True):
            raise ValueError(f"the action {self.action} lacks what it acts on")
        return self


class Reply(BaseModel):
    """One message the AI said, as the screen shows it."""

    text: str
    payload: dict = {}


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    turn: dict


_pool: AsyncConnectionPool[Any] | None = None
_graph: CompiledStateGraph | None = None
_opening = asyncio.Lock()


async def graph() -> CompiledStateGraph:
    global _pool, _graph
    async with _opening:
        if _graph is None:
            conninfo = get_settings().database_url.replace("+psycopg", "", 1)
            pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
                conninfo,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                open=False,
            )
            await pool.open()
            saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
            await saver.setup()
            _pool, _graph = pool, _build().compile(checkpointer=saver)
        return _graph


async def close() -> None:
    """Release the Chat threads' connections; the next turn opens them again."""
    global _pool, _graph
    pool, _pool, _graph = _pool, None, None
    if pool is not None:
        await pool.close()


def _build() -> StateGraph:
    return (
        StateGraph(State)
        .add_node("upload", _upload)
        .add_node("decide", _decide)
        .add_node("generate", _generate)
        .add_node("revise", _revise)
        .add_node("retire", _retire)
        .add_conditional_edges(START, _attached, ["upload", "decide"])
        .add_conditional_edges("decide", _acts, ["generate", "revise", "retire", END])
        .add_edge("upload", END)
        .add_edge("generate", END)
        .add_edge("revise", END)
        .add_edge("retire", END)
    )


def _attached(_: State, config: RunnableConfig) -> Literal["upload", "decide"]:
    return "upload" if config.get("configurable", {}).get("file") else "decide"


def _acts(state: State) -> str:
    action = state["turn"]["action"]
    return END if action == "ask" else action


def _chat_id(config: RunnableConfig) -> str:
    return config.get("configurable", {})["thread_id"]


async def _say(chat_id: str, text: str, payload: dict | None = None) -> dict:
    await chat.post_message(chat_id, text, payload)
    return {"messages": [AIMessage(text, additional_kwargs={"payload": payload or {}})]}


async def _numbered(chat_id: str) -> list[str]:
    ids = await chat.chat_item_ids(chat_id)
    found = {i.id: i for i in await records.get_items(ids)}
    lines = []
    for number, item_id in enumerate(ids, 1):
        item = found[item_id]
        text = " ".join(item.version.text.split())[:LISTED_TEXT]
        lines.append(f"{number}. {'(wyrzucone) ' if item.retired else ''}{text}")
    return lines


def _topics() -> str:
    return "\n".join(f"{t.id}: {t.name}" for s in curriculum() for t in s.topics)


async def _upload(state: State, config: RunnableConfig) -> dict:
    chat_id = _chat_id(config)
    filename, data = config.get("configurable", {})["file"]
    started = await request_upload(chat_id, filename, data)
    return await _say(
        chat_id,
        f"Przetwarzam plik {filename}. Zadania z niego trafią do tego czatu.",
        {
            "upload_id": str(started.upload_id),
            "job_id": str(started.job_id),
            "filename": filename,
        },
    )


async def _decide(state: State, config: RunnableConfig) -> dict:
    listing = await _numbered(_chat_id(config))
    system = CHAT.format(items="\n".join(listing) or "(brak)", topics=_topics())
    turn = await llm.ask("items.chat", Turn, [SystemMessage(system), *state["messages"]])
    update = {"turn": turn.model_dump(mode="json")}
    if turn.action == "ask":
        update |= await _say(_chat_id(config), turn.reply)
    return update


async def _generate(state: State, config: RunnableConfig) -> dict:
    chat_id = _chat_id(config)
    turn = Turn.model_validate(state["turn"])
    assert turn.spec is not None
    job_id = await request_generation(turn.spec, GenerationOrigin(kind="chat", chat_id=chat_id))
    return await _say(chat_id, turn.reply, {"job_id": str(job_id)})


async def _find(chat_id: str, number: int):
    """The Chat's Item with this number, or the answer to say when there is none."""
    ids = await chat.chat_item_ids(chat_id)
    if not 1 <= number <= len(ids):
        return None, f"W tym czacie nie ma zadania numer {number}; jest ich {len(ids)}."
    (item,) = await records.get_items([ids[number - 1]])
    return item, ""


async def _revise(state: State, config: RunnableConfig) -> dict:
    chat_id = _chat_id(config)
    turn = Turn.model_validate(state["turn"])
    assert turn.number is not None
    item, missing = await _find(chat_id, turn.number)
    if item is None:
        return await _say(chat_id, missing)
    if item.retired:
        return await _say(chat_id, f"Zadanie {turn.number} jest wyrzucone.")
    current = ItemContent.model_validate(item.version.model_dump())
    brief = {"zadanie": current.model_dump(mode="json"), "polecenie": turn.instruction}
    draft = await llm.ask(
        "items.revise",
        Draft,
        [SystemMessage(REVISE), HumanMessage(json.dumps(brief, ensure_ascii=False))],
    )
    tags = await tagging.default_tagger().tag("\n".join([draft.text, *draft.options.values()]))
    try:
        content = ItemContent.model_validate(
            draft.model_dump()
            | {
                f: getattr(tags, f)
                for f in ("difficulty", "curriculum_topics", "general_requirements")
            }
        )
    except ValidationError:
        return await _say(
            chat_id,
            f"Nie udało się przepisać zadania {turn.number}. Spróbuj opisać zmianę inaczej.",
        )
    await records.new_version(item.id, content)
    (revised,) = await records.get_items([item.id])
    return await _say(
        chat_id, turn.reply, {"item_id": str(item.id), "version": revised.version.number}
    )


async def _retire(state: State, config: RunnableConfig) -> dict:
    chat_id = _chat_id(config)
    turn = Turn.model_validate(state["turn"])
    assert turn.number is not None
    item, missing = await _find(chat_id, turn.number)
    if item is None:
        return await _say(chat_id, missing)
    await records.retire_item(item.id)
    return await _say(chat_id, turn.reply, {"item_id": str(item.id), "retired": True})


async def take_turn(
    chat_id: str, text: str, file: tuple[str, bytes] | None = None
) -> AsyncIterator[Reply]:
    """The Teacher's message, with a file perhaps; yields what the AI says as it says it."""
    await chat.get_chat(chat_id)
    if not text.strip() and file is None:
        raise ValueError("an empty message")
    await chat.name_after(chat_id, text)
    await chat.post_message(chat_id, text, {"file": file[0]} if file else None, role="user")
    said = f"[załączony plik: {file[0]}] {text}".strip() if file else text
    config: RunnableConfig = {"configurable": {"thread_id": chat_id, "file": file}}
    with llm.trace("items.chat", chat_id=chat_id):
        async for update in (await graph()).astream(
            {"messages": [HumanMessage(said)]}, config, stream_mode="updates"
        ):
            for step in update.values():
                for message in (step or {}).get("messages", []):
                    if isinstance(message, AIMessage):
                        yield Reply(
                            text=message.text, payload=message.additional_kwargs.get("payload", {})
                        )


async def delete_chat(chat_id: str) -> None:
    """The Chat, its messages and its thread; the Items it made stay in the bank."""
    await chat.forget_chat(chat_id)
    await (await graph()).checkpointer.adelete_thread(chat_id)  # type: ignore[union-attr]
