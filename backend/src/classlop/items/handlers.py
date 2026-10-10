import uuid

from classlop.items import exemplars, generation, index
from classlop.shared.jobs import Progress, handler
from classlop.shared.models import Job


@handler("items.reindex")
async def reindex(job: Job, progress: Progress) -> None:
    await index.reindex(uuid.UUID(job.payload["item_id"]))


@handler("items.load_knowledge_base")
async def load_knowledge_base(job: Job, progress: Progress) -> dict:
    return {"exemplars": await exemplars.load(job.payload["key"])}


@handler("items.generate")
async def generate(job: Job, progress: Progress) -> dict:
    return await generation.generate(generation.Request.model_validate(job.payload), progress)
