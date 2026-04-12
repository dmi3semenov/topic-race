"""
Проверяет ``build_event_frames`` — преобразование сырого DataFrame сообщений
в список кадров для bar chart race (по одному кадру на каждое сообщение).

Это сердце анимации: каждый кадр это snapshot кумулятивных счётчиков
«сколько постов в каком топике» на момент N-го сообщения. Если здесь что-то
сломается, на графике пропадут сообщения или начнут двоиться.

Тесты покрывают:
    • пустой DataFrame → пустой список кадров,
    • одно сообщение → один кадр с count=1,
    • несколько сообщений → правильное нарастание кумулятивных счётчиков
      с учётом порядка по времени,
    • фильтр по since обрезает старые события,
    • downsampling через max_frames сохраняет финальный кадр,
    • поле ``display_name`` имеет приоритет над ``topic_title`` (нужно для
      disambiguation одноимённых топиков — см. баг про два «Изучить»).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from topic_race.animate import build_event_frames


def _df(rows: list[tuple[datetime, str]], use_display_name: bool = True) -> pd.DataFrame:
    data = {
        "date": [r[0] for r in rows],
        "topic_title": [r[1] for r in rows],
        "topic_id": [hash(r[1]) % 1000 for r in rows],
    }
    if use_display_name:
        data["display_name"] = data["topic_title"]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"], utc=True)
    return df


def test_пустой_df_даёт_пустой_список() -> None:
    df = _df([])
    assert build_event_frames(df) == []


def test_одно_сообщение_один_кадр() -> None:
    t = datetime(2025, 6, 7, tzinfo=timezone.utc)
    frames = build_event_frames(_df([(t, "LLM")]))
    assert len(frames) == 1
    assert frames[0].counts == {"LLM": 1}


def test_кумулятивные_счётчики_по_нескольким_топикам() -> None:
    start = datetime(2025, 6, 7, tzinfo=timezone.utc)
    rows = [
        (start + timedelta(hours=0), "LLM"),
        (start + timedelta(hours=1), "ML"),
        (start + timedelta(hours=2), "LLM"),
        (start + timedelta(hours=3), "ML"),
        (start + timedelta(hours=4), "LLM"),
    ]
    frames = build_event_frames(_df(rows))
    assert len(frames) == 5
    assert frames[0].counts == {"LLM": 1}
    assert frames[1].counts == {"LLM": 1, "ML": 1}
    assert frames[2].counts == {"LLM": 2, "ML": 1}
    assert frames[3].counts == {"LLM": 2, "ML": 2}
    assert frames[4].counts == {"LLM": 3, "ML": 2}


def test_фильтр_since_обрезает_старые_события() -> None:
    start = datetime(2025, 6, 7, tzinfo=timezone.utc)
    rows = [
        (start + timedelta(days=0), "A"),
        (start + timedelta(days=5), "A"),
        (start + timedelta(days=10), "A"),
    ]
    frames = build_event_frames(
        _df(rows),
        since=start + timedelta(days=4),
    )
    assert len(frames) == 2
    # Внутри отфильтрованного окна счётчик идёт заново от 1
    assert frames[0].counts == {"A": 1}
    assert frames[-1].counts == {"A": 2}


def test_max_frames_прореживает_но_сохраняет_финальный_кадр() -> None:
    start = datetime(2025, 6, 7, tzinfo=timezone.utc)
    rows = [(start + timedelta(minutes=i), "X") for i in range(200)]
    frames = build_event_frames(_df(rows), max_frames=20)

    assert len(frames) <= 25  # 20 прореженных + принудительно добавленный последний
    # Финальный кадр отражает истинное финальное число, независимо от downsampling
    assert frames[-1].counts == {"X": 200}


def test_display_name_имеет_приоритет_над_topic_title() -> None:
    """Это нужно для disambiguation одноимённых топиков: если display_name
    присутствует (как в реальной load_messages_df после колонизации дублей
    «Изучить»), агрегация должна ключеваться по нему, а не по ``topic_title``."""
    t = datetime(2025, 6, 7, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "date": pd.to_datetime([t, t + timedelta(hours=1)], utc=True),
        "topic_id": [1, 2],
        "topic_title": ["Изучить", "Изучить"],  # одно и то же название
        "display_name": ["Изучить #1", "Изучить #2"],  # но разведены суффиксом
    })
    frames = build_event_frames(df)
    assert frames[-1].counts == {"Изучить #1": 1, "Изучить #2": 1}
