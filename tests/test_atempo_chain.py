"""
Проверяет ``_atempo_chain`` — построение цепочки фильтров ffmpeg atempo.

Зачем это нужно: фильтр ``atempo`` в ffmpeg принимает значения только в
диапазоне [0.5, 2.0] за один вызов. Чтобы ускорить в 3x/4x или замедлить
в 4x, нужно соединить несколько atempo через запятую — а ещё не вставлять
вырожденный «atempo=1.0» (это шумит в команде и может сбивать форматтер).

Эти тесты гарантируют:
    • тождественный темп 1.0 даёт пустой фильтр (noop),
    • одиночные значения в диапазоне форматируются без хвостовых нулей,
    • 2.0× и 0.5× не расщепляются на дубли,
    • 3×/4×/0.25× корректно строят цепочки,
    • нулевые и отрицательные тем — пустой фильтр.
"""
from __future__ import annotations

from topic_race.render_video import _atempo_chain


def test_темп_1_это_noop() -> None:
    assert _atempo_chain(1.0) == ""


def test_темп_1p5_без_хвостовых_нулей() -> None:
    assert _atempo_chain(1.5) == "atempo=1.5"


def test_темп_2_не_расщепляется() -> None:
    """2.0 входит в один вызов atempo. Не должно быть избыточного
    второго сегмента atempo=1.0."""
    assert _atempo_chain(2.0) == "atempo=2.0"


def test_темп_3_строит_цепочку() -> None:
    """3x = 2.0 * 1.5 — две последовательных atempo."""
    result = _atempo_chain(3.0)
    parts = result.split(",")
    assert parts[0] == "atempo=2.0"
    assert parts[1].startswith("atempo=1.5")


def test_темп_4_строит_цепочку_двух_двоек() -> None:
    assert _atempo_chain(4.0) == "atempo=2.0,atempo=2.0"


def test_темп_0p5_не_расщепляется() -> None:
    assert _atempo_chain(0.5) == "atempo=0.5"


def test_темп_0p25_строит_цепочку() -> None:
    assert _atempo_chain(0.25) == "atempo=0.5,atempo=0.5"


def test_ноль_и_отрицательные_дают_пустой_фильтр() -> None:
    assert _atempo_chain(0) == ""
    assert _atempo_chain(-1) == ""
