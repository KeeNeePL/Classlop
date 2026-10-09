import asyncio
import json
from functools import lru_cache

import boto3

from classlop.shared.settings import get_settings

MAX_RECEIVES = 3


@lru_cache
def _client():
    s = get_settings()
    secret = s.aws_secret_access_key
    return boto3.client(
        "sqs",
        endpoint_url=s.sqs_endpoint_url,
        region_name=s.aws_region,
        aws_access_key_id=s.aws_access_key_id,
        aws_secret_access_key=secret.get_secret_value() if secret else None,
    )


@lru_cache
def url() -> str:
    """The jobs queue. In dev it and its dead-letter queue are created on first use; prod's
    come from the stack."""
    s, sqs = get_settings(), _client()
    if not s.sqs_endpoint_url:
        return sqs.get_queue_url(QueueName=s.jobs_queue)["QueueUrl"]
    dlq = sqs.create_queue(QueueName=s.jobs_dlq)["QueueUrl"]
    dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])["Attributes"][
        "QueueArn"
    ]
    redrive = {"deadLetterTargetArn": dlq_arn, "maxReceiveCount": MAX_RECEIVES}
    return sqs.create_queue(
        QueueName=s.jobs_queue,
        Attributes={
            "VisibilityTimeout": str(s.jobs_visibility_timeout),
            "RedrivePolicy": json.dumps(redrive),
        },
    )["QueueUrl"]


def dlq_url() -> str:
    return _client().get_queue_url(QueueName=get_settings().jobs_dlq)["QueueUrl"]


async def send(body: dict) -> None:
    await asyncio.to_thread(_client().send_message, QueueUrl=url(), MessageBody=json.dumps(body))


async def receive(wait_seconds: int = 2) -> list[dict]:
    response = await asyncio.to_thread(
        _client().receive_message,
        QueueUrl=url(),
        MaxNumberOfMessages=5,
        WaitTimeSeconds=wait_seconds,
    )
    return response.get("Messages", [])


async def delete(message: dict) -> None:
    await asyncio.to_thread(
        _client().delete_message, QueueUrl=url(), ReceiptHandle=message["ReceiptHandle"]
    )


async def retry_in(message: dict, seconds: int) -> None:
    await asyncio.to_thread(
        _client().change_message_visibility,
        QueueUrl=url(),
        ReceiptHandle=message["ReceiptHandle"],
        VisibilityTimeout=seconds,
    )
