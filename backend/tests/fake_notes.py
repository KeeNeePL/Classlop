"""The Notes the dashboard keeps, in memory, for tests and the Playwright server."""


class InMemoryNotes:
    def __init__(self) -> None:
        self.kept: dict[tuple[str, str], str] = {}

    async def delete_class(self, class_id: str) -> None:
        self.kept = {k: v for k, v in self.kept.items() if k[0] != class_id}
