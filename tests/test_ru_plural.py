"""Tests for Russian number-word agreement — the exact bug that produced
'761 постов' instead of the correct '761 пост'."""
from __future__ import annotations

import pytest

from topic_race.render_video import ru_plural


FORMS = ("пост", "поста", "постов")


@pytest.mark.parametrize(
    "n, expected",
    [
        # Small singulars / few / many
        (0, "постов"),
        (1, "пост"),
        (2, "поста"),
        (3, "поста"),
        (4, "поста"),
        (5, "постов"),
        (10, "постов"),
        # The 11..14 exception — they're always "many" even though digit could be 1/2/3/4
        (11, "постов"),
        (12, "постов"),
        (13, "постов"),
        (14, "постов"),
        # 15..20 — many
        (15, "постов"),
        (20, "постов"),
        # 21..24 repeat the pattern
        (21, "пост"),
        (22, "поста"),
        (23, "поста"),
        (24, "поста"),
        (25, "постов"),
        # 100, 101, 111
        (100, "постов"),
        (101, "пост"),
        (111, "постов"),
        (112, "постов"),
        # 761 — the case from the real bug report
        (761, "пост"),
        (762, "поста"),
        (765, "постов"),
    ],
)
def test_ru_plural_post(n: int, expected: str) -> None:
    assert ru_plural(n, *FORMS) == expected


def test_ru_plural_accepts_negative() -> None:
    # Negative numbers get normalized to their absolute value.
    assert ru_plural(-1, *FORMS) == "пост"
    assert ru_plural(-11, *FORMS) == "постов"
    assert ru_plural(-22, *FORMS) == "поста"


def test_ru_plural_topic_words() -> None:
    forms = ("топик", "топика", "топиков")
    assert ru_plural(1, *forms) == "топик"
    assert ru_plural(2, *forms) == "топика"
    assert ru_plural(5, *forms) == "топиков"
    assert ru_plural(81, *forms) == "топик"  # another real case
