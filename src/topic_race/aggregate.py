from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

BinFreq = Literal["h", "D", "W"]


def load_messages_df(conn: sqlite3.Connection, chat_id: int) -> pd.DataFrame:
    df = pd.read_sql_query(
        """
        SELECT m.date, m.topic_id, m.message_id, m.grouped_id,
               t.title AS topic_title, t.icon_emoji
        FROM messages m
        LEFT JOIN topics t ON t.chat_id = m.chat_id AND t.topic_id = m.topic_id
        WHERE m.chat_id = ?
        """,
        conn,
        params=(chat_id,),
    )
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df["topic_title"] = df["topic_title"].fillna(df["topic_id"].astype(str))

    # Collapse media albums: Telegram returns each photo/video in an album as a
    # separate Message, but users see one "post". Rows with the same non-null
    # grouped_id in the same topic are one logical post — keep only the earliest.
    if "grouped_id" in df.columns:
        has_group = df["grouped_id"].notna()
        solo = df[~has_group]
        album = (
            df[has_group]
            .sort_values("message_id")
            .drop_duplicates(subset=["topic_id", "grouped_id"], keep="first")
        )
        df = pd.concat([solo, album], ignore_index=True).sort_values("date")

    # Disambiguate duplicate titles: different topic_ids with the same title get a
    # suffix `#<id>`, so the aggregation (which groups by display_name) doesn't merge
    # them. We also expose topic_id itself so callers can debug.
    title_topic_count = df.groupby("topic_title")["topic_id"].nunique()
    dupes = set(title_topic_count[title_topic_count > 1].index)
    df["display_name"] = df.apply(
        lambda r: f"{r['topic_title']} #{r['topic_id']}" if r["topic_title"] in dupes
        else r["topic_title"],
        axis=1,
    )
    return df


def build_race_frame(
    df: pd.DataFrame,
    bin_freq: BinFreq = "D",
    since: datetime | None = None,
    until: datetime | None = None,
) -> pd.DataFrame:
    """Returns a wide, cumulative DataFrame ready for bar_chart_race.

    Index: time buckets. Columns: topic titles. Values: cumulative message counts.
    """
    if df.empty:
        return pd.DataFrame()

    work = df.copy()
    if since is not None:
        work = work[work["date"] >= since]
    if until is not None:
        work = work[work["date"] <= until]
    if work.empty:
        return pd.DataFrame()

    work["bucket"] = work["date"].dt.floor(bin_freq)

    counts = (
        work.groupby(["bucket", "topic_title"]).size().unstack(fill_value=0).sort_index()
    )

    full_index = pd.date_range(counts.index.min(), counts.index.max(), freq=bin_freq)
    counts = counts.reindex(full_index, fill_value=0)
    counts.index.name = "bucket"

    cumulative = counts.cumsum()
    return cumulative
