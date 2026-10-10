from functools import lru_cache

import boto3
from botocore.config import Config

from classlop.shared.settings import get_settings


@lru_cache
def _client(public: bool = False):
    s = get_settings()
    endpoint = (public and s.s3_public_endpoint_url) or s.s3_endpoint_url
    secret = s.aws_secret_access_key
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=s.aws_region,
        aws_access_key_id=s.aws_access_key_id,
        aws_secret_access_key=secret.get_secret_value() if secret else None,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def put(key: str, body: bytes, content_type: str) -> None:
    _client().put_object(
        Bucket=get_settings().s3_bucket, Key=key, Body=body, ContentType=content_type
    )


def get(key: str) -> bytes:
    return _client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def delete(key: str) -> None:
    _client().delete_object(Bucket=get_settings().s3_bucket, Key=key)


def presigned_url(key: str, expires_in: int = 300) -> str:
    """A short-lived GET URL the browser can open."""
    return _client(public=True).generate_presigned_url(
        "get_object", Params={"Bucket": get_settings().s3_bucket, "Key": key}, ExpiresIn=expires_in
    )


def ping() -> None:
    _client().head_bucket(Bucket=get_settings().s3_bucket)
