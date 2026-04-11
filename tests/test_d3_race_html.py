"""
Smoke-тесты шаблона ``make_d3_race_html``.

Реальную D3-анимацию тут не рендерим (нужен браузер) — вместо этого
проверяем, что HTML собран корректно и все параметры из Python доходят
до клиентского DATA. Покрываем:
    • базовую структуру (есть <svg>, подключён d3, плейсхолдеры заменены),
    • флаг вертикального layout доезжает до body-класса и высота 1920,
    • intro_lines рендерятся server-side в DOM — нужно, чтобы intro-слайд
      был виден с первого кадра и не мигал поверх гонки (см. баг flash
      перед intro),
    • HTML-escape опасных символов в intro-строках,
    • защита от закрытия <script> через ``</script>`` внутри JSON payload
      (если пользователь передаст такой intro_lines — мы не должны
      прерывать собственный script-блок),
    • subtitle принимает список строк,
    • пустой frames не роняет генератор.
"""
from __future__ import annotations

from datetime import datetime, timezone

from topic_race.animate import EventFrame
from topic_race.d3_race import make_d3_race_html


def _frame(sec: int, **counts: int) -> EventFrame:
    return EventFrame(
        timestamp=datetime(2025, 6, 7, 12, 0, sec, tzinfo=timezone.utc),
        counts=dict(counts),
    )


def test_базовая_структура_html() -> None:
    frames = [_frame(0, LLM=1), _frame(1, LLM=1, ML=1), _frame(2, LLM=2, ML=1)]
    html, height = make_d3_race_html(frames, title="Тест", subtitle="подзаголовок")
    assert "<svg" in html
    assert "d3.v7" in html
    assert "__DATA_JSON__" not in html, "плейсхолдер должен быть подставлен"
    assert height > 0


def test_вертикальный_layout_флаг_доходит_до_payload() -> None:
    frames = [_frame(0, LLM=1)]
    html, height = make_d3_race_html(frames, layout="vertical")
    assert "vertical" in html
    assert height == 1920


def test_intro_рендерится_в_html_и_body_получает_класс_has_intro() -> None:
    """Если intro_lines передан, intro-блок должен быть полностью собран
    server-side, а body получает класс ``has-intro``. Это нужно, чтобы
    CSS скрывал гонку и показывал intro с самого первого кадра — без
    этого возникает баг flash перед intro (мы его видели в ранней версии)."""
    frames = [_frame(0, LLM=1)]
    html, _ = make_d3_race_html(
        frames,
        intro_lines=["Topic Race", "Группа «Материалы»"],
        autoplay=True,
        hide_controls=True,
    )
    assert "has-intro" in html
    assert "hide-controls" in html
    assert "Topic Race" in html
    assert "Группа «Материалы»" in html


def test_html_экранирует_опасные_символы_в_intro() -> None:
    """Произвольный intro-текст может содержать HTML-спецсимволы.
    Они должны превратиться в сущности в видимом DOM, а закрывающий тег
    ``</script>`` — не появиться как прерыватель нашего <script>-блока."""
    frames = [_frame(0, LLM=1)]
    html, _ = make_d3_race_html(
        frames,
        intro_lines=["<script>alert('xss')</script>"],
    )
    # В видимом <div id="intro"> угловые скобки экранируются.
    assert "&lt;script&gt;" in html
    # Внутри встроенного JSON-блока </script не должен встречаться больше раз,
    # чем настоящие закрывающие теги (их ровно 2: один для <script src=d3>,
    # один для нашего inline-скрипта).
    count_close = html.count("</script>")
    assert count_close == 2, f"ожидал 2 </script>, получили {count_close}"


def test_subtitle_принимает_список_строк() -> None:
    frames = [_frame(0, LLM=1)]
    html, _ = make_d3_race_html(
        frames,
        subtitle=["строка 1", "строка 2"],
    )
    assert "строка 1" in html
    assert "строка 2" in html


def test_title_принимает_список_строк() -> None:
    """Для вертикального Reels title разбит на 2 строки (чтобы длинная
    «Популярные топики в группе «{group_name}»» не упиралась в правый край).
    Проверяем, что обе строки доезжают до payload."""
    frames = [_frame(0, LLM=1)]
    html, _ = make_d3_race_html(
        frames,
        title=["Популярные топики в группе", "«Материалы»"],
    )
    assert "Популярные топики в группе" in html
    assert "«Материалы»" in html


def test_пустой_список_frames_не_ломает_генератор() -> None:
    html, height = make_d3_race_html([])
    assert "<svg" in html
    assert height > 0
