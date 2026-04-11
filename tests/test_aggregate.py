"""
Проверяет ``aggregate.load_messages_df`` — чтение сообщений из SQLite с
двумя важными преобразованиями: свёртка media-альбомов и disambiguation
одноимённых топиков.

Контекст багов:
    • media-альбомы: Telegram возвращает каждую фотографию альбома как
      отдельное Message, но пользователь воспринимает это как ОДИН пост.
      В ранней версии счётчик Openclaw показывал 21, хотя реально постов 19
      (2 альбома по 2 фото каждый = 2 «лишних» кадра).
    • одноимённые топики: в группе «Материалы» есть два топика с названием
      «Изучить» (topic_id=425 и 859). Ранняя агрегация сливала их по
      названию и давала 12 вместо правильных 7 и 5 раздельно.

Эти тесты работают на in-memory SQLite с настоящей production-схемой,
чтобы ловить изменения как в SQL, так и в pandas-пре/постобработке.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from topic_race.aggregate import load_messages_df
from topic_race.storage import (
    MessageRow,
    SCHEMA,
    TopicRow,
    insert_messages,
    upsert_group,
    upsert_topics,
)


def _make_conn() -> sqlite3.Connection:
    """In-memory SQLite с production-схемой, как в реальном cache.db."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def test_два_сообщения_одного_альбома_сворачиваются_в_один_пост() -> None:
    conn = _make_conn()
    chat_id = 42
    upsert_group(conn, chat_id, "TestGroup")
    upsert_topics(conn, [TopicRow(chat_id=chat_id, topic_id=100, title="Openclaw", icon_emoji=None)])

    t0 = datetime(2026, 2, 19, tzinfo=timezone.utc)
    insert_messages(conn, [
        # Два сообщения одного media-альбома — это один логический пост
        MessageRow(chat_id=chat_id, topic_id=100, message_id=918, date=t0, from_id=1, grouped_id=999),
        MessageRow(chat_id=chat_id, topic_id=100, message_id=919, date=t0, from_id=1, grouped_id=999),
        # Обычное сообщение без grouped_id — отдельный пост
        MessageRow(chat_id=chat_id, topic_id=100, message_id=920, date=t0 + timedelta(days=1), from_id=1, grouped_id=None),
    ])
    conn.commit()

    df = load_messages_df(conn, chat_id)

    # 3 сырых сообщения → 2 логических поста после свёртки альбома
    assert len(df) == 2
    titles = df["topic_title"].tolist()
    assert titles.count("Openclaw") == 2


def test_обычные_сообщения_без_альбома_не_сворачиваются() -> None:
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


def test_display_name_разводит_дубль_названия_топиков() -> None:
    """Два топика с именем «Изучить» должны получить суффикс ``#<topic_id>``
    и считаться раздельно. Единственный «LLM» остаётся без суффикса."""
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

    disambiguated = set(df[df["topic_title"] == "Изучить"]["display_name"])
    assert disambiguated == {"Изучить #425", "Изучить #859"}
    assert df[df["topic_title"] == "LLM"]["display_name"].iloc[0] == "LLM"
