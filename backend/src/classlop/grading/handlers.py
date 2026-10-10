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
        await announce(request)
        return
    await grade_graph.ainvoke({"job": request})
