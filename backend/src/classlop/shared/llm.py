import os

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

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
