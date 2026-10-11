"""The Bank zadań screen's `Bank` in memory, with a few invented Items, for tests and for the
Playwright server, which run without a database or a search index."""

import uuid
from datetime import UTC, datetime

from classlop.dashboard.bank import ClassOption, UsageEntry
from classlop.items import (
    Filters,
    Item,
    ItemContent,
    ItemEdit,
    ItemVersion,
    RubricLevel,
    SearchPage,
    SectionCount,
    curriculum,
)
from classlop.items.index import section_of
from classlop.items.types import Difficulty

TOPICS = {t.id: t for s in curriculum() for t in s.topics}
CLASSES = [
    ClassOption(id=uuid.UUID(int=n), name=name) for n, name in ((1, "1A"), (2, "2C"), (3, "3B"))
]
THEN = datetime(2026, 9, 1, 8, tzinfo=UTC)


def content(topic: str, **kw) -> ItemContent:
    fields = (
        dict(
            item_format="open",
            points=2,
            difficulty="medium",
            curriculum_topics=[TOPICS[topic]],
            general_requirements=["II"],
        )
        | kw
    )
    if fields["item_format"] == "open":
        fields |= dict(
            answer=fields.get("answer", "$x = 1$"),
            model_solution=fields.get("model_solution", "$x = 1$, bo $x - 1 = 0$."),
            rubric=fields.get("rubric", [RubricLevel(points=2, description="Poprawny wynik.")]),
        )
    else:
        fields |= dict(
            points=1,
            options={"A": "$1$", "B": "$2$", "C": "$4$", "D": "$8$"},
            correct_options=["B"],
        )
    return ItemContent(**fields)


SEED: list[tuple[ItemContent, dict]] = [
    (
        content(
            "lo2024:III.4",
            text=r"Rozwiąż równanie $x^2 - 4x - 5 = 0$.",
            answer="$x_1 = -1$, $x_2 = 5$",
            model_solution=r"$\Delta = 36$, więc $x_1 = -1$ i $x_2 = 5$.",
            rubric=[
                RubricLevel(points=1, description=r"Obliczenie $\Delta = 36$."),
                RubricLevel(points=2, description="Oba pierwiastki."),
            ],
        ),
        dict(used=[(2, "2C", "Funkcja kwadratowa", 0.72)]),
    ),
    (
        content(
            "lo2024:II.1",
            item_format="closed",
            difficulty="easy",
            text="Wartość wyrażenia $(a+b)^2 - a^2 - b^2$ dla $a = 2$, $b = 3$ jest równa:",
        ),
        dict(flag="Brak pasującego wzorca"),
    ),
    (
        content(
            "lo2024:V.2",
            difficulty="hard",
            text="Dla funkcji $f(x) = 2x^2 - 3x$ oblicz $f(-2)$.",
            answer="$14$",
            model_solution="$f(-2) = 2 \\cdot 4 + 6 = 14$.",
        ),
        dict(used=[(1, "1A", "Wzory skróconego mnożenia", 0.4), (3, "3B", None, None)]),
    ),
    (content("lo2024:I.1", item_format="closed", difficulty="easy", text="Ile to $2^3 - 6$?"), {}),
    (
        content("lo2024:IV.1", text="Rozwiąż układ równań $x + y = 3$, $x - y = 1$."),
        dict(flag="Niepewny odczyt skanu"),
    ),
    (
        content("lo2024:VI.4", item_format="closed", text="Który ciąg jest arytmetyczny?"),
        dict(flag="Brak pasującego wzorca"),
    ),
    (content("lo2024:II.1", difficulty="easy", text="Rozwiń $(x - 3)^2$."), dict(retired=True)),
    (
        content(
            "lo2024:III.4",
            item_format="closed",
            difficulty="hard",
            text="Ile pierwiastków ma $x^2 + 1$?",
        ),
        dict(flag="Podobne do zadania w banku"),
    ),
]


class InMemoryBank:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Back to the invented Items as they were seeded."""
        self.items: dict[uuid.UUID, Item] = {}
        self._usage: dict[uuid.UUID, list[UsageEntry]] = {}
        self.classes_used: dict[uuid.UUID, set[uuid.UUID]] = {}
        for n, (version, extra) in enumerate(SEED, start=1):
            item_id = uuid.UUID(int=1000 + n)
            self.items[item_id] = Item(
                id=item_id,
                origin="chat",
                origin_ref=None,
                source_file=None,
                source_page=None,
                exemplar_ids=[],
                flagged="flag" in extra,
                flag_reason=extra.get("flag"),
                retired=extra.get("retired", False),
                created_at=THEN.replace(minute=n),
                version=ItemVersion(
                    id=uuid.UUID(int=2000 + n),
                    item_id=item_id,
                    number=1,
                    created_at=THEN.replace(minute=n),
                    **version.model_dump(),
                ),
            )
            self._usage[item_id] = [
                UsageEntry(
                    assignment_id=f"01J{n:023d}",
                    title=title,
                    class_id=f"01K{c:023d}",
                    class_name=name,
                    given_at=THEN.replace(day=2 + c),
                    average=average,
                )
                for c, name, title, average in extra.get("used", [])
            ]
            self.classes_used[item_id] = {uuid.UUID(int=c) for c, *_ in extra.get("used", [])}
        # Every version ever made: an edit leaves the pinned ones readable.
        self._versions = {i.version.id: i.version for i in self.items.values()}

    async def search(self, query: str, filters: Filters, page: int, size: int) -> SearchPage:
        def matches(i: Item) -> bool:
            v, f = i.version, filters
            topics = {t.id for t in v.curriculum_topics}
            return (
                query.lower() in v.text.lower()
                and (not f.difficulty or v.difficulty in f.difficulty)
                and (not f.curriculum_topics or topics & set(f.curriculum_topics))
                and (
                    not f.curriculum_sections
                    or {section_of(t) for t in topics} & set(f.curriculum_sections)
                )
                and (f.item_format is None or v.item_format == f.item_format)
                and (f.retired is None or i.retired == f.retired)
                and (f.flagged is None or i.flagged == f.flagged)
                and (
                    f.never_used_with_class is None
                    or f.never_used_with_class not in self.classes_used[i.id]
                )
            )

        found = sorted((i for i in self.items.values() if matches(i)), key=lambda i: i.created_at)
        start = (page - 1) * size
        return SearchPage(
            items=found[::-1][start : start + size], total=len(found), page=page, size=size
        )

    async def get(self, item_id: uuid.UUID) -> Item:
        if item_id not in self.items:
            raise LookupError(item_id)
        return self.items[item_id]

    async def get_many(self, item_ids: list[uuid.UUID]) -> list[Item]:
        return [await self.get(i) for i in item_ids]

    async def versions(self, version_ids: list[uuid.UUID]) -> list[ItemVersion]:
        if missing := set(version_ids) - self._versions.keys():
            raise LookupError(f"no version {sorted(missing)}")
        return [self._versions[i] for i in version_ids]

    @staticmethod
    def _in(item: Item, section: str) -> bool:
        return section in {section_of(t.id) for t in item.version.curriculum_topics}

    async def stock(self, never_used_with: uuid.UUID | None) -> list[SectionCount]:
        counts: dict[tuple[str, Difficulty], int] = {}
        for i in self.items.values():
            if i.retired or never_used_with in self.classes_used[i.id]:
                continue
            for section in {section_of(t.id) for t in i.version.curriculum_topics}:
                key = (section, i.version.difficulty)
                counts[key] = counts.get(key, 0) + 1
        return [SectionCount(section=s, difficulty=d, count=n) for (s, d), n in counts.items()]

    async def pick(
        self,
        section: str,
        difficulty: Difficulty,
        n: int,
        class_id: uuid.UUID,
        *,
        allow_reuse: bool,
        exclude: list[uuid.UUID],
    ) -> list[Item]:
        """The oldest Items first, where the real pick is random."""
        found = [
            i
            for i in sorted(self.items.values(), key=lambda i: i.created_at)
            if not i.retired
            and self._in(i, section)
            and i.version.difficulty == difficulty
            and i.id not in exclude
            and (allow_reuse or class_id not in self.classes_used[i.id])
        ]
        return found[:n]

    def give(self, item_ids: list[uuid.UUID], class_id: uuid.UUID) -> list[uuid.UUID]:
        """As `items.give`: the Class has now got them; returns the versions pinned."""
        for i in item_ids:
            self.classes_used[i].add(class_id)
        return [self.items[i].version.id for i in item_ids]

    async def usage(self, item_id: uuid.UUID) -> list[UsageEntry]:
        return self._usage[item_id]

    async def classes(self) -> list[ClassOption]:
        return CLASSES

    async def edit(self, item_id: uuid.UUID, changes: ItemEdit) -> None:
        item = await self.get(item_id)
        data = item.version.model_dump(exclude={"id", "item_id", "number", "created_at"})
        version = ItemContent.model_validate(data | dict(changes))
        self.items[item_id] = item.model_copy(
            update=dict(
                flagged=False,
                flag_reason=None,
                version=ItemVersion(
                    id=uuid.uuid4(),
                    item_id=item_id,
                    number=item.version.number + 1,
                    created_at=datetime.now(UTC),
                    **version.model_dump(),
                ),
            )
        )
        self._versions[self.items[item_id].version.id] = self.items[item_id].version

    async def _set(self, item_id: uuid.UUID, **values) -> None:
        self.items[item_id] = (await self.get(item_id)).model_copy(update=values)

    async def retire(self, item_id: uuid.UUID) -> None:
        await self._set(item_id, retired=True)

    async def restore(self, item_id: uuid.UUID) -> None:
        await self._set(item_id, retired=False)

    async def dismiss_flag(self, item_id: uuid.UUID) -> None:
        await self._set(item_id, flagged=False, flag_reason=None)

    def add(self, version: ItemContent, origin_ref: str | None = None) -> Item:
        """A new Item, as a Generation request or an upload makes one."""
        n = len(self.items) + 1
        item_id = uuid.UUID(int=1000 + n)
        now = datetime.now(UTC)
        item = Item(
            id=item_id,
            origin="chat",
            origin_ref=origin_ref,
            source_file=None,
            source_page=None,
            exemplar_ids=[],
            flagged=False,
            flag_reason=None,
            retired=False,
            created_at=now,
            version=ItemVersion(
                id=uuid.UUID(int=2000 + n),
                item_id=item_id,
                number=1,
                created_at=now,
                **version.model_dump(),
            ),
        )
        self.items[item_id] = item
        self._usage[item_id] = []
        self.classes_used[item_id] = set()
        self._versions[item.version.id] = item.version
        return item
