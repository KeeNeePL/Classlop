from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment variables: `.env` in dev, Secrets Manager in prod. Defaults fit dev."""

    # ../.env is the repo root when run from backend/.
    model_config = SettingsConfigDict(env_file=("../.env", ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://classlop:classlop@localhost:5432/classlop"
    opensearch_url: str = "http://localhost:9200"

    aws_region: str = "eu-central-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: SecretStr | None = None
    s3_bucket: str = "classlop"
    s3_endpoint_url: str | None = None
    # Where the browser reaches S3 when it differs from s3_endpoint_url (MinIO inside compose).
    s3_public_endpoint_url: str | None = None

    sqs_endpoint_url: str | None = None
    jobs_queue: str = "classlop-jobs"
    jobs_dlq: str = "classlop-jobs-dlq"
    jobs_visibility_timeout: int = 60
    # Seconds before a failed job is redelivered.
    jobs_retry_delay: int = 10
    # Set in prod: timed triggers go to EventBridge Scheduler instead of the shared.schedule table.
    schedule_group: str | None = None
    schedule_role_arn: str | None = None
    jobs_queue_arn: str | None = None

    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_chat_model: str = "gpt-5.4-mini"
    llm_embedding_model: str = "text-embedding-ada-002"
    llm_models: dict[str, str] = {}

    langsmith_api_key: SecretStr | None = None
    langsmith_endpoint: str = "https://eu.api.smith.langchain.com"
    langsmith_project: str = "classlop"


@lru_cache
def get_settings() -> Settings:
    return Settings()
