import uuid
from datetime import datetime

from classlop.grading.common_mistakes import recompute, request_if_computed, superseded
from classlop.grading.graph import GradeJob, announce, grade_graph
from classlop.grading.result import result
from classlop.shared.jobs import Progress, handler
from classlop.shared.models import Job


@handler("grading.grade")
async def grade(job: Job, progress: Progress) -> None:
    request = GradeJob.model_validate(job.payload)
    # SQS delivers at least once: a finished result is never graded or written again, and
    # announcing it again is a no-op unless the first run died before announcing.
    if await result(request.submission_id, request.handed_in_at) is not None:
        await announce(request.submission_id, request.handed_in_at, first=True)
        await request_if_computed(request.assignment_id)
        return
    await grade_graph.ainvoke({"job": request})


@handler("grading.common_mistakes")
async def gather_common_mistakes(job: Job, progress: Progress) -> None:
    """`teams` enqueues it at the due time; a recompute request enqueues it with its time."""
    assignment_id = uuid.UUID(job.payload["assignment_id"])
    requested_at = job.payload.get("requested_at")
    if requested_at and await superseded(assignment_id, datetime.fromisoformat(requested_at)):
        return
    await recompute(assignment_id)
