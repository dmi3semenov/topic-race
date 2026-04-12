"""
Проверяет функцию ``build_schedule`` — генератор расписания длительностей
кадров для bar chart race.

Зачем это нужно: реальное видео должно динамически менять темп:
    • медленно в начале (читается первое появление новых топиков),
    • быстро в середине (плотные всплески активности не занимают весь ролик),
    • очень медленно в конце (драматичная концовка под замедление музыки).

Эти тесты фиксируют форму кривой темпа для всех поддерживаемых режимов
(linear, ease-in, ease-out, ease-in-out), а также проверяют, что:
    • суммарная длительность соответствует заданной (с учётом min_ms-флора),
    • ease-in-out действительно ассиметричный (конец медленнее, чем старт),
    • пустые/единичные случаи не ломают функцию.
"""
from __future__ import annotations

import pytest

from topic_race.render_video import build_schedule


def test_пустой_список_и_один_кадр() -> None:
    assert build_schedule(0, 5000) == []
    out = build_schedule(1, 5000)
    assert len(out) == 1
    assert out[0] == pytest.approx(5000, abs=1)


def test_linear_даёт_равномерное_расписание() -> None:
    out = build_schedule(10, 1000, pacing="linear")
    assert len(out) == 10
    assert min(out) == max(out)  # все равны


def test_сумма_расписания_совпадает_с_целью() -> None:
    """Расписание должно примерно суммироваться к запрошенной длительности.

    ease-in / ease-out могут давать дрейф до ~10% из-за ``min_ms``-флора:
    первые кадры в ease-in имеют микроскопические веса и упираются в пол
    40мс, раздувая сумму. Это допустимый компромисс — иначе ранние кадры
    пролетали бы за миллисекунды.
    """
    for pacing in ("linear", "ease-in-out"):
        out = build_schedule(100, 10_000, pacing=pacing)
        total = sum(out)
        assert abs(total - 10_000) < 500, f"{pacing}: {total=}"

    for pacing in ("ease-in", "ease-out"):
        out = build_schedule(100, 10_000, pacing=pacing)
        total = sum(out)
        assert 9500 <= total <= 11500, f"{pacing}: {total=}"


def test_ease_out_медленно_в_начале_быстро_в_конце() -> None:
    out = build_schedule(200, 20_000, pacing="ease-out")
    first = sum(out[:10]) / 10
    last = sum(out[-10:]) / 10
    assert first > last, "ease-out должен замедляться к концу"


def test_ease_in_быстро_в_начале_медленно_в_конце() -> None:
    out = build_schedule(200, 20_000, pacing="ease-in")
    first = sum(out[:10]) / 10
    last = sum(out[-10:]) / 10
    assert first < last


def test_ease_in_out_быстрее_всего_в_середине() -> None:
    """Ассиметричный колокол: края медленные, середина быстрая,
    и конец медленнее начала (default end_mult > start_mult)."""
    out = build_schedule(200, 20_000, pacing="ease-in-out")
    first = sum(out[:20]) / 20
    middle = sum(out[90:110]) / 20
    last = sum(out[-20:]) / 20

    assert middle < first
    assert middle < last
    # Концовка по умолчанию медленнее, чем intro (драматичный финал)
    assert last > first


def test_ease_in_out_уважает_мультипликаторы() -> None:
    """Если задать большой end_mult, кадры финала должны быть существенно
    длиннее кадров начала."""
    out = build_schedule(
        200, 20_000, pacing="ease-in-out",
        start_mult=1.2, end_mult=3.0,
    )
    first = out[0]
    last = out[-1]
    ratio = last / first
    assert 2.0 < ratio < 3.2, f"ratio={ratio}"


def test_min_ms_пол_уважается() -> None:
    out = build_schedule(100, 50, pacing="linear", min_ms=40)
    assert all(ms >= 40 for ms in out)


def test_неизвестный_режим_ломается() -> None:
    with pytest.raises(ValueError):
        build_schedule(10, 1000, pacing="warp-speed")
