"""Tests for aggregate.load_messages_df — album collapsing and disambiguation."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pandas as pd

from topic_race.aggregate import load_messages_df
from topic_race.storage import MessageRow, insert_messages, upsert_group, upsert_topics
from topic_race.storage import TopicRow


def _make_conn() -> sqlite3.Connection:
    """In-memory SQLite seeded with the production schema."""
    conn = sqlite3.connect(":memory:")
    from topic_race.storage import SCHEMA
    conn.executescript(SCHEMA)
    return conn


def test_album_collapse_two_grouped_messages_become_one() -> None:
    conn = _make_conn()
    chat_id = 42
    upsert_group(conn, chat_id, "TestGroup")
    upsert_topics(conn, [TopicRow(chat_id=chat_id, topic_id=100, title="Openclaw", icon_emoji=None)])

    t0 = datetime(2026, 2, 19, tzinfo=timezone.utc)
    insert_messages(conn, [
        # Two messages of the same media album: should count as 1
        MessageRow(chat_id=chat_id, topic_id=100, message_id=918, date=t0, from_id=1, grouped_id=999),
        MessageRow(chat_id=chat_id, topic_id=100, message_id=919, date=t0, from_id=1, grouped_id=999),
        # Solo message (no grouping) — counts normally
        MessageRow(chat_id=chat_id, topic_id=100, message_id=920, date=t0 + timedelta(days=1), from_id=1, grouped_id=None),
    ])
    conn.commit()

    df = load_messages_df(conn, chat_id)

    # 3 raw messages → 2 logical posts after collapse
    assert len(df) == 2
    titles = df["topic_title"].tolist()
    assert titles.count("Openclaw") == 2


def test_solo_messages_are_not_collapsed() -> None:
    conn = _make_conn()
    chat_id = 42
    upsert_group(conn, chat_id, "TestGroup")
    upsert_topics(conn, [TopicRow(chat_id=chat_id, topic_id=100, title="LLM", icon_emoji=None)])
    t0 = datetime(2026, 2, 19, tzinfo=timezone.utc)
    insert_messages(conn, [
        MessageRow(chat_id=chat_id, topic_id=100, message_id=i, date=t0 + timedelta(hours=i), from_id=1, grouped_id=None)
        for i in range(1, 6)
    ])
    conn.commit()

    df = load_messages_df(conn, chat_id)
    assert len(df) == 5


def test_display_name_disambiguates_duplicate_titles() -> None:
    conn = _make_conn()
    chat_id = 42
    upsert_group(conn, chat_id, "TestGroup")
    upsert_topics(conn, [
        TopicRow(chat_id=chat_id, topic_id=425, title="Изучить", icon_emoji=None),
        TopicRow(chat_id=chat_id, topic_id=859, title="Изучить", icon_emoji=None),
        TopicRow(chat_id=chat_id, topic_id=999, title="LLM", icon_emoji=None),
    ])
    t0 = datetime(2026, 2, 19, tzinfo=timezone.utc)
    insert_messages(conn, [
        MessageRow(chat_id=chat_id, topic_id=425, message_id=1, date=t0, from_id=1, grouped_id=None),
        MessageRow(chat_id=chat_id, topic_id=859, message_id=2, date=t0, from_id=1, grouped_id=None),
        MessageRow(chat_id=chat_id, topic_id=999, message_id=3, date=t0, from_id=1, grouped_id=None),
    ])
    conn.commit()

    df = load_messages_df(conn, chat_id)

    # Duplicate titles get a #<topic_id> suffix
    disambiguated = set(df[df["topic_title"] == "Изучить"]["display_name"])
    assert disambiguated == {"Изучить #425", "Изучить #859"}
    # Non-duplicate titles are unchanged
    assert df[df["topic_title"] == "LLM"]["display_name"].iloc[0] == "LLM"
