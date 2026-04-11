from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .config import CACHE_DB


SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    chat_id     INTEGER PRIMARY KEY,
    title       TEXT NOT NULL,
    fetched_at  TEXT
);

CREATE TABLE IF NOT EXISTS topics (
    chat_id     INTEGER NOT NULL,
    topic_id    INTEGER NOT NULL,
    title       TEXT NOT NULL,
    icon_emoji  TEXT,
    created_at  TEXT,
    PRIMARY KEY (chat_id, topic_id)
);

CREATE TABLE IF NOT EXISTS messages (
    chat_id     INTEGER NOT NULL,
    topic_id    INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    date        TEXT NOT NULL,
    from_id     INTEGER,
    grouped_id  INTEGER,
    PRIMARY KEY (chat_id, topic_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_topic ON messages(chat_id, topic_id);
"""


@dataclass
class TopicRow:
    chat_id: int
    topic_id: int
    title: str
    icon_emoji: str | None


@dataclass
class MessageRow:
    chat_id: int
    topic_id: int
    message_id: int
    date: datetime
    from_id: int | None
    grouped_id: int | None = None


@contextmanager
def connect(db_path: Path = CACHE_DB) -> Iterator[sqlite3.Connection]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_group(conn: sqlite3.Connection, chat_id: int, title: str) -> None:
    conn.execute(
        """
        INSERT INTO groups (chat_id, title, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title, fetched_at=excluded.fetched_at
        """,
        (chat_id, title, datetime.now(timezone.utc).isoformat()),
    )


def upsert_topics(conn: sqlite3.Connection, topics: Iterable[TopicRow]) -> None:
    conn.executemany(
        """
        INSERT INTO topics (chat_id, topic_id, title, icon_emoji, created_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, topic_id) DO UPDATE SET
            title=excluded.title,
            icon_emoji=excluded.icon_emoji
        """,
        [
            (t.chat_id, t.topic_id, t.title, t.icon_emoji, datetime.now(timezone.utc).isoformat())
            for t in topics
        ],
    )


def insert_messages(conn: sqlite3.Connection, rows: Iterable[MessageRow]) -> int:
    cur = conn.executemany(
        """
        INSERT OR IGNORE INTO messages (chat_id, topic_id, message_id, date, from_id, grouped_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (m.chat_id, m.topic_id, m.message_id, m.date.isoformat(), m.from_id, m.grouped_id)
            for m in rows
        ],
    )
    return cur.rowcount or 0


def max_message_id(conn: sqlite3.Connection, chat_id: int, topic_id: int) -> int:
    cur = conn.execute(
        "SELECT COALESCE(MAX(message_id), 0) FROM messages WHERE chat_id=? AND topic_id=?",
        (chat_id, topic_id),
    )
    return cur.fetchone()[0]


def list_topics(conn: sqlite3.Connection, chat_id: int) -> list[TopicRow]:
    cur = conn.execute(
        "SELECT chat_id, topic_id, title, icon_emoji FROM topics WHERE chat_id=?",
        (chat_id,),
    )
    return [TopicRow(*row) for row in cur.fetchall()]
