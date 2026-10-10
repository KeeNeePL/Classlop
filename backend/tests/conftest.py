import asyncio
import os
import sys
import uuid

# Before any settings are read: private queues, so a running compose worker never steals jobs.
os.environ.setdefault("SQS_ENDPOINT_URL", "http://localhost:9324")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:8333")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "dev")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "dev")
_run = uuid.uuid4().hex[:8]
os.environ["JOBS_QUEUE"] = f"test-jobs-{_run}"
os.environ["JOBS_DLQ"] = f"test-jobs-dlq-{_run}"
os.environ["JOBS_VISIBILITY_TIMEOUT"] = "5"
os.environ["JOBS_RETRY_DELAY"] = "1"

if sys.platform == "win32":
    # psycopg's async mode cannot run on the default Proactor loop.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
