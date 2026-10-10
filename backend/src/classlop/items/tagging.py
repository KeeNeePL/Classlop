from typing import Protocol

from classlop.items.types import Tags


class Tagger(Protocol):
    async def tag(self, text: str) -> Tags: ...


class _Unbuilt:
    async def tag(self, text: str) -> Tags:
        raise NotImplementedError("Tagging arrives with #38")


def default_tagger() -> Tagger:
    return _Unbuilt()
