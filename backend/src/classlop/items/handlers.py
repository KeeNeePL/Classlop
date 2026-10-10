import uuid

from classlop.items import index
from classlop.shared.jobs import Progress, handler
from classlop.shared.models import Job


@handler("items.reindex")
async def reindex(job: Job, progress: Progress) -> None:
    await index.reindex(uuid.UUID(job.payload["item_id"]))
