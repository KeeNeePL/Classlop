"""`teams` enqueues `grading.grade`; `teams` and `dashboard` read `result`."""

from classlop.grading.handlers import grade
from classlop.grading.result import ItemResult, Reason, Result, result

__all__ = ["ItemResult", "Reason", "Result", "grade", "result"]
