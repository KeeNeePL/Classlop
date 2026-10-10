import functools
import inspect
import json
import os
import re
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from datetime import datetime

import langsmith
from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import BaseModel

from classlop.shared.settings import Settings, get_settings


def chat_model(job: str) -> ChatOpenAI:
    """The chat model for a job key such as "grading.transcribe"."""
    s = get_settings()
    return ChatOpenAI(
        model=s.llm_models.get(job, s.llm_chat_model),
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        default_headers=_key_header(s),
    )


async def ask[T: BaseModel](job: str, schema: type[T], messages: list[BaseMessage]) -> T:
    """A reply in `schema` from the job's chat model, traced under the job's key."""
    reply = await (
        chat_model(job)
        .bind(response_format=schema)
        .ainvoke(messages, config={"run_name": job, "tags": [job]})
    )
    return schema.model_validate(_clean(json.loads(reply.text)))


# Every C0 control character but tab and newline, and DEL. Models occasionally emit them,
# and Postgres refuses NUL in text.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _clean(value):
    if isinstance(value, str):
        return _CONTROL.sub("", value)
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def embeddings() -> OpenAIEmbeddings:
    s = get_settings()
    return OpenAIEmbeddings(
        model=s.llm_embedding_model,
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        default_headers=_key_header(s),
    )


def _key_header(s: Settings) -> dict[str, str] | None:
    # The team endpoint is Azure API Management: it ignores Bearer and reads this header.
    return {"api-key": s.llm_api_key.get_secret_value()} if s.llm_api_key else None


# The only values a trace's metadata carries: references, never content such as a Student's
# text, and nothing a new payload field adds unreviewed.
TRACED_KEYS = ("job_id", "submission_id", "handed_in_at", "assignment_id", "item_id")


@contextmanager
def trace(name: str, **values: object) -> Iterator[None]:
    """One LangSmith trace for the model calls made inside, tagged with `name`, with the
    `TRACED_KEYS` among `values` as metadata; nothing is sent while tracing is off."""
    metadata = {
        k: v.isoformat() if isinstance(v, datetime) else str(v)
        for k, v in values.items()
        if k in TRACED_KEYS
    }
    with langsmith.trace(name, run_type="chain", tags=[name], metadata=metadata):
        yield


def traced[**P, T](name: str) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """`trace` around an async action, with its arguments offered as the metadata."""

    def decorate(action: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        signature = inspect.signature(action)

        @functools.wraps(action)
        async def run(*args: P.args, **kwargs: P.kwargs) -> T:
            with trace(name, **signature.bind(*args, **kwargs).arguments):
                return await action(*args, **kwargs)

        return run

    return decorate


def configure_tracing() -> None:
    """LangSmith reads the environment, which .env does not reach outside compose."""
    s = get_settings()
    if s.langsmith_api_key:
        os.environ.update(
            LANGSMITH_TRACING="true",
            LANGSMITH_ENDPOINT=s.langsmith_endpoint,
            LANGSMITH_API_KEY=s.langsmith_api_key.get_secret_value(),
            LANGSMITH_PROJECT=s.langsmith_project,
        )
