import logging
import uuid
from datetime import datetime

from classlop.grading.common_mistakes import recompute, request_if_computed, superseded
from classlop.grading.graph import GradeJob, announce, grade_graph, store_failure
from classlop.grading.result import result
from classlop.shared.jobs import Progress, handler
from classlop.shared.models import Job

log = logging.getLogger(__name__)


@handler("grading.grade", traced=True)
async def grade(job: Job, progress: Progress) -> None:
    request = GradeJob.model_validate(job.payload)
    # SQS delivers at least once: a finished result is never graded or written again, and
    # announcing it again is a no-op unless the first run died before announcing. A failed
    # result is graded again: that is Oceń ponownie.
    found = await result(request.submission_id, request.handed_in_at)
    if found is not None and found.status != "failed":
        await announce(request.submission_id, request.handed_in_at, status=found.status)
        await request_if_computed(request.assignment_id)
        return
    try:
        await grade_graph.ainvoke({"job": request})
    except Exception:
        # Earlier attempts fail so SQS retries; the last one leaves the Teacher a Held result.
        if not job.final_attempt:
            raise
        log.exception("grading %s failed on its last attempt", request.submission_id)
        await store_failure(request)


@handler("grading.common_mistakes", traced=True)
async def gather_common_mistakes(job: Job, progress: Progress) -> None:
    """`teams` enqueues it at the due time; a recompute request enqueues it with its time."""
    assignment_id = uuid.UUID(job.payload["assignment_id"])
    requested_at = job.payload.get("requested_at")
    if requested_at and await superseded(assignment_id, datetime.fromisoformat(requested_at)):
        return
    await recompute(assignment_id)
