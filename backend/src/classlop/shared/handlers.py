from classlop.shared.jobs import Progress, handler
from classlop.shared.models import Job


@handler("shared.ping")
async def ping(job: Job, progress: Progress) -> dict:
    await progress({"step": "pong"})
    return {"pong": True}
