"""Tests for event-frame aggregation (the data flowing into the D3 race)."""
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


def test_empty_df() -> None:
    df = _df([])
    assert build_event_frames(df) == []


def test_single_message_one_frame() -> None:
    t = datetime(2025, 6, 7, tzinfo=timezone.utc)
    frames = build_event_frames(_df([(t, "LLM")]))
    assert len(frames) == 1
    assert frames[0].counts == {"LLM": 1}


def test_cumulative_counts_across_topics() -> None:
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


def test_since_filter_drops_old_events() -> None:
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
    # Within the filtered window, the running count restarts from 1
    assert frames[0].counts == {"A": 1}
    assert frames[-1].counts == {"A": 2}


def test_max_frames_downsamples_but_keeps_final() -> None:
    start = datetime(2025, 6, 7, tzinfo=timezone.utc)
    rows = [(start + timedelta(minutes=i), "X") for i in range(200)]
    frames = build_event_frames(_df(rows), max_frames=20)

    assert len(frames) <= 25  # 20 + the forced last event
    # Last frame reflects the true final count regardless of downsampling
    assert frames[-1].counts == {"X": 200}


def test_uses_display_name_when_present() -> None:
    """display_name is what disambiguates duplicate-titled topics.

    If it's present, aggregation should key off it rather than topic_title."""
    t = datetime(2025, 6, 7, tzinfo=timezone.utc)
    df = pd.DataFrame({
        "date": pd.to_datetime([t, t + timedelta(hours=1)], utc=True),
        "topic_id": [1, 2],
        "topic_title": ["Изучить", "Изучить"],  # same title
        "display_name": ["Изучить #1", "Изучить #2"],  # but disambiguated
    })
    frames = build_event_frames(df)
    assert frames[-1].counts == {"Изучить #1": 1, "Изучить #2": 1}
