import json

from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage
from pydantic import BaseModel, SecretStr

from classlop.shared import llm
from classlop.shared.settings import Settings


def test_a_job_key_overrides_the_default_chat_model(monkeypatch):
    settings = Settings(
        llm_api_key=SecretStr("x"), llm_models={"grading.transcription": "vision-model"}
    )
    monkeypatch.setattr(llm, "get_settings", lambda: settings)

    assert llm.chat_model("grading.transcription").model_name == "vision-model"
    assert llm.chat_model("items.generation").model_name == "gpt-5.4-mini"


def test_the_key_also_goes_in_an_api_key_header(monkeypatch):
    # The team endpoint is Azure API Management, which rejects Bearer.
    settings = Settings(llm_api_key=SecretStr("secret"))
    monkeypatch.setattr(llm, "get_settings", lambda: settings)

    assert llm.chat_model("grading.transcribe").default_headers == {"api-key": "secret"}
    assert llm.embeddings().default_headers == {"api-key": "secret"}


class Part(BaseModel):
    text: str


class Reply(BaseModel):
    title: str
    parts: list[Part]


async def test_control_characters_are_removed_from_every_reply_string(monkeypatch):
    # Postgres refuses NUL in text, and the model once sent "\x03\x00" and "\x7f" in Feedback.
    raw = {"title": "Zad.\x005", "parts": [{"text": "kąt \x03\x00da\x7f\nz\tbokiem"}]}
    model = GenericFakeChatModel(messages=iter([AIMessage(json.dumps(raw))]))
    monkeypatch.setattr(llm, "chat_model", lambda job: model)

    reply = await llm.ask("grading.score", Reply, [HumanMessage("?")])

    assert reply == Reply(title="Zad.5", parts=[Part(text="kąt da\nz\tbokiem")])
