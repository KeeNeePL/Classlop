from classlop.grading.graph import GradeJob, grade_graph
from classlop.shared.jobs import Progress, handler
from classlop.shared.models import Job


@handler("grading.grade")
async def grade(job: Job, progress: Progress) -> None:
    await grade_graph.ainvoke({"job": GradeJob.model_validate(job.payload)})
