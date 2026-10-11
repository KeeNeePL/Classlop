"""The Suggested grade: a school grade 1 to 6 from a percent, under the Teacher's thresholds."""

from collections.abc import Sequence

# The lowest percent for grades 2 to 6, until the Teacher sets their own.
THRESHOLDS = (30, 50, 70, 85, 100)


def suggested_grade(earned: int, available: int, thresholds: Sequence[int] = THRESHOLDS) -> int:
    """On the real ratio, like Wymagają uwagi: 84.6% rounds to 85% on screen but is still a 4."""
    return 1 + sum(100 * earned >= t * available for t in thresholds)
