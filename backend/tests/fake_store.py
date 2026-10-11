"""The dashboard's own records in memory, for tests and for the Playwright server, which run
without a database."""

from classlop.dashboard.reports.grades import THRESHOLDS


class InMemoryStore:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._notes: dict[tuple[str, str], str] = {}
        self._thresholds = list(THRESHOLDS)

    async def note(self, class_id: str, student_id: str) -> str:
        return self._notes.get((class_id, student_id), "")

    async def save_note(self, class_id: str, student_id: str, text: str) -> None:
        self._notes[(class_id, student_id)] = text

    async def thresholds(self) -> list[int]:
        return list(self._thresholds)

    async def save_thresholds(self, percents: list[int]) -> None:
        self._thresholds = list(percents)
