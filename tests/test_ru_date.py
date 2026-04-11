"""Tests for Russian date formatting."""
from __future__ import annotations

from datetime import datetime, timezone

from topic_race.render_video import ru_date


def test_ru_date_basic() -> None:
    assert ru_date(datetime(2025, 6, 7, tzinfo=timezone.utc)) == "7 июня 2025"
    assert ru_date(datetime(2026, 4, 11, tzinfo=timezone.utc)) == "11 апреля 2026"


def test_ru_date_all_months() -> None:
    expected = [
        (1, "января"), (2, "февраля"), (3, "марта"),
        (4, "апреля"), (5, "мая"), (6, "июня"),
        (7, "июля"), (8, "августа"), (9, "сентября"),
        (10, "октября"), (11, "ноября"), (12, "декабря"),
    ]
    for month, word in expected:
        assert word in ru_date(datetime(2025, month, 1))


def test_ru_date_naive_datetime_ok() -> None:
    # Works even without tzinfo — we only format the fields.
    assert ru_date(datetime(2025, 1, 1)) == "1 января 2025"
