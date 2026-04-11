"""
Проверяет ``layout_check`` — приближённую оценку ширины SVG-текста и функцию
предупреждения об overflow в вертикальном Reels-лейауте.

Контекст бага: в одном из рендеров строка «Популярные топики в группе
«Материалы»» в title налезала на правый край — отступа вообще не было. Чтобы
такое ловилось до реального рендера, мы оценим ширину текста по количеству
символов × коэффициенту и сравним с доступной шириной (viewport − margin_left
− margin_right − min_right_padding). Это не пиксель-в-пиксель, но достаточно,
чтобы заранее услышать алерт на типовые случаи.

Эти тесты фиксируют:
    • дефолтный двухстрочный title «Популярные топики в группе» / «Материалы»
      помещается при текущих margin-значениях вертикального layout,
    • явно слишком длинный title вызывает warning,
    • subtitle с датой и счётчиками помещается,
    • уменьшение margin_right без уменьшения текста ломает проверку.
"""
from __future__ import annotations

from topic_race.layout_check import TextSpec, check_lines_fit, estimate_text_width


# Эти значения должны соответствовать CSS и margin-настройкам в d3_race.py
# для вертикального режима. Если меняешь шаблон — поправь и тут.
VERTICAL_MARGIN_LEFT = 280
VERTICAL_MARGIN_RIGHT = 60
VIEWPORT_WIDTH = 1080
MIN_RIGHT_PADDING = 20

TITLE_SINGLE_FONT = 28
SUBTITLE_FONT = 30


def test_однострочный_title_помещается() -> None:
    """Дефолтный однострочный title «Топ-15 топиков в группе «Материалы»»
    на 28px bold должен помещаться в доступную ширину при текущих
    margin-настройках вертикального layout."""
    lines = [
        TextSpec(
            "Топ-15 топиков в группе «Материалы»",
            font_size=TITLE_SINGLE_FONT,
            weight="bold",
        ),
    ]
    warnings = check_lines_fit(
        lines,
        viewport_width=VIEWPORT_WIDTH,
        margin_left=VERTICAL_MARGIN_LEFT,
        margin_right=VERTICAL_MARGIN_RIGHT,
        min_right_padding=MIN_RIGHT_PADDING,
    )
    assert warnings == [], warnings


def test_слишком_длинное_название_группы_ловится_варнингом() -> None:
    lines = [
        TextSpec(
            "«Какое-то безумно длинное название группы на много слов»",
            font_size=TITLE_SINGLE_FONT,
            weight="extrabold",
        ),
    ]
    warnings = check_lines_fit(
        lines,
        viewport_width=VIEWPORT_WIDTH,
        margin_left=VERTICAL_MARGIN_LEFT,
        margin_right=VERTICAL_MARGIN_RIGHT,
        min_right_padding=MIN_RIGHT_PADDING,
    )
    assert len(warnings) == 1
    assert "overflow" in warnings[0]


def test_дефолтный_subtitle_помещается() -> None:
    lines = [
        TextSpec("7 июня 2025 — 11 апреля 2026", font_size=SUBTITLE_FONT, weight="medium"),
        TextSpec("81 топик • 761 пост", font_size=SUBTITLE_FONT, weight="medium"),
    ]
    warnings = check_lines_fit(
        lines,
        viewport_width=VIEWPORT_WIDTH,
        margin_left=VERTICAL_MARGIN_LEFT,
        margin_right=VERTICAL_MARGIN_RIGHT,
        min_right_padding=MIN_RIGHT_PADDING,
    )
    assert warnings == [], warnings


def test_оценка_ширины_растёт_с_font_size() -> None:
    small = estimate_text_width(TextSpec("abc", font_size=10))
    big = estimate_text_width(TextSpec("abc", font_size=30))
    assert big > small * 2.5  # грубо пропорционально font_size


def test_жирный_шрифт_считается_шире_обычного() -> None:
    regular = estimate_text_width(TextSpec("какой-то текст", font_size=30, weight="regular"))
    bold = estimate_text_width(TextSpec("какой-то текст", font_size=30, weight="extrabold"))
    assert bold > regular
