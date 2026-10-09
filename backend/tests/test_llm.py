from pydantic import SecretStr

from classlop.shared import llm
from classlop.shared.settings import Settings


def test_a_job_key_overrides_the_default_chat_model(monkeypatch):
    settings = Settings(
        llm_api_key=SecretStr("x"), llm_models={"grading.transcription": "vision-model"}
    )
    monkeypatch.setattr(llm, "get_settings", lambda: settings)

    assert llm.chat_model("grading.transcription").model_name == "vision-model"
    assert llm.chat_model("items.generation").model_name == "gpt-5.4-mini"
