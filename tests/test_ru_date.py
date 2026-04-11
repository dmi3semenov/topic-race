"""
Проверяет ``ru_date`` — форматирование даты на русском в виде «7 июня 2025».

Эта строка уходит и в title, и в subtitle, и в intro-слайд. Если месяц
сдвинется на один (off-by-one) или попадёт неправильное слово — это сразу
видно зрителю. Тесты фиксируют:
    • формат «день месяц год»,
    • все 12 названий месяцев в правильных падежах,
    • что наивный datetime без таймзоны тоже работает (функция форматирует
      только локальные поля даты).
"""
from __future__ import annotations

from datetime import datetime, timezone

from topic_race.render_video import ru_date


def test_базовый_формат_даты() -> None:
    assert ru_date(datetime(2025, 6, 7, tzinfo=timezone.utc)) == "7 июня 2025"
    assert ru_date(datetime(2026, 4, 11, tzinfo=timezone.utc)) == "11 апреля 2026"


def test_все_месяцы_в_правильных_падежах() -> None:
    expected = [
        (1, "января"), (2, "февраля"), (3, "марта"),
        (4, "апреля"), (5, "мая"), (6, "июня"),
        (7, "июля"), (8, "августа"), (9, "сентября"),
        (10, "октября"), (11, "ноября"), (12, "декабря"),
    ]
    for month, word in expected:
        assert word in ru_date(datetime(2025, month, 1))


def test_наивный_datetime_работает() -> None:
    # Функция форматирует только год/месяц/день — tzinfo не обязателен.
    assert ru_date(datetime(2025, 1, 1)) == "1 января 2025"
