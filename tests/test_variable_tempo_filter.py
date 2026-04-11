"""
Проверяет ``build_variable_tempo_filter`` — построение ffmpeg filter_complex
для переменного темпа аудио (slow → fast → slow).

Зачем это нужно: пользователь хочет, чтобы музыка «Universe Size» в начале
первые ~10 секунд играла на обычной скорости (пока идёт intro-слайд), в
середине ускорялась до 2x (основная гонка пролетает бодро), а к концу
плавно замедлялась (драматичный финал, музыка не обрезается жёстко, а
будто допевает в замедлении). Это строится как 3 сегмента через atrim +
atempo + concat.

Тесты покрывают:
    • корректное время начала/конца каждого сегмента в исходном аудио,
    • формат filter_complex — содержит atrim, atempo, concat, fade-out,
    • выходной label — ``aout`` (это то, что потом маппится в -map),
    • валидация входа: intro+outro не должны быть больше target,
    • нулевые/отрицательные тем-параметры должны ломаться.
"""
from __future__ import annotations

import pytest

from topic_race.render_video import build_variable_tempo_filter


def test_типовой_slow_fast_slow_фильтр() -> None:
    """Реальный сценарий: 120 сек общее, старт с 40й секунды источника,
    10 сек intro 1.0x, главная часть 2.0x, 8 сек финал 0.6x."""
    filt, labels = build_variable_tempo_filter(
        audio_start_sec=40,
        target_duration_sec=120,
        intro_sec=10,
        intro_tempo=1.0,
        main_tempo=2.0,
        outro_sec=8,
        outro_tempo=0.6,
    )
    assert labels[-1] == "aout"

    # Должен содержать 3 сегмента с правильными временными границами
    # Intro: source 40..50 (10 сек * 1.0 = 10 сек)
    assert "atrim=40.0:50.0" in filt
    # Main: source 50..254 (102 сек * 2.0 = 204 сек → 50..254)
    assert "atrim=50.0:254.0" in filt
    # Outro: source 254..258.8 (8 сек * 0.6 = 4.8 сек → 254..258.8)
    assert "atrim=254.0:258.8" in filt

    # Все нужные операции на месте
    assert "concat=n=3" in filt
    assert "volume=0.55" in filt
    assert "afade=t=in" in filt
    assert "afade=t=out" in filt
    # Main segment использует atempo=2.0
    assert "atempo=2.0" in filt


def test_intro_без_ускорения_не_вставляет_atempo_1() -> None:
    """Если intro_tempo=1.0, для этого сегмента не должно быть избыточного
    atempo — только ``anull`` (passthrough). Иначе ffmpeg ругается на
    вырожденный фильтр."""
    filt, _ = build_variable_tempo_filter(
        audio_start_sec=0,
        target_duration_sec=100,
        intro_sec=10,
        intro_tempo=1.0,
        main_tempo=2.0,
        outro_sec=10,
        outro_tempo=0.5,
    )
    # Внутри первого сегмента после запятой должен быть anull (passthrough),
    # а не пустая строка или atempo=1.0
    first_segment = filt.split("[s2]")[0]
    assert "anull" in first_segment


def test_слишком_короткий_target_относительно_intro_outro_ломается() -> None:
    with pytest.raises(ValueError):
        build_variable_tempo_filter(
            audio_start_sec=0,
            target_duration_sec=15,  # 10+8 > 15
            intro_sec=10,
            outro_sec=8,
        )


def test_аудио_вход_настраивается_через_label() -> None:
    """Регрессия: в реальном _mux вход #0 — это webm без аудио, а аудио
    лежит во входе #1. Фильтр должен уметь ссылаться на произвольный label,
    иначе ffmpeg падает с «Stream specifier :a not found»."""
    filt, _ = build_variable_tempo_filter(
        audio_start_sec=40,
        target_duration_sec=120,
        audio_input_label="1:a",
    )
    # Все три atrim должны быть с [1:a], а не с [0:a]
    assert "[1:a]atrim" in filt
    assert "[0:a]atrim" not in filt


def test_нулевой_или_отрицательный_темп_ломается() -> None:
    with pytest.raises(ValueError):
        build_variable_tempo_filter(
            audio_start_sec=0,
            target_duration_sec=100,
            main_tempo=0,
        )
    with pytest.raises(ValueError):
        build_variable_tempo_filter(
            audio_start_sec=0,
            target_duration_sec=100,
            outro_tempo=-1,
        )
