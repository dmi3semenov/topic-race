from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from telethon import TelegramClient

from .config import Settings, load_settings
from .storage import (
    MessageRow,
    connect,
    insert_messages,
    upsert_group,
    upsert_topics,
)
from .telegram_client import GroupInfo, fetch_topic_messages, fetch_topics, find_group, make_client

log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]


async def sync_group(
    client: TelegramClient,
    settings: Settings,
    since: datetime | None = None,
    progress: ProgressFn | None = None,
) -> tuple[GroupInfo, int, int]:
    """Fetch topics & messages into the local cache. Returns (group, topics, new msgs)."""
    notify = progress or (lambda _m: None)

    notify(f"Ищу группу «{settings.group_name}»…")
    group = await find_group(client, settings.group_name)
    notify(f"Нашёл: {group.title} (chat_id={group.chat_id}, forum={group.is_forum})")

    if not group.is_forum:
        raise RuntimeError(f"Group {group.title!r} is not a forum (topics disabled)")

    notify("Тяну список топиков…")
    topics = await fetch_topics(client, group)
    notify(f"Топиков: {len(topics)}")

    total_new = 0
    with connect() as conn:
        upsert_group(conn, group.chat_id, group.title)
        upsert_topics(conn, topics)
        conn.commit()

        for i, topic in enumerate(topics, 1):
            notify(f"[{i}/{len(topics)}] Сообщения топика «{topic.title}»…")
            batch: list[MessageRow] = []
            async for msg in fetch_topic_messages(client, group, topic, since=since):
                batch.append(msg)
                if len(batch) >= 500:
                    total_new += insert_messages(conn, batch)
                    conn.commit()
                    batch.clear()
            if batch:
                total_new += insert_messages(conn, batch)
                conn.commit()

    notify(f"Готово. Новых сообщений: {total_new}")
    return group, len(topics), total_new


def run_sync(
    since_days: int | None = 14,
    progress: ProgressFn | None = None,
) -> tuple[GroupInfo, int, int]:
    """Synchronous wrapper — boots Telethon, runs sync_group, returns stats."""
    settings = load_settings()
    since = (
        datetime.now(timezone.utc) - timedelta(days=since_days)
        if since_days is not None
        else None
    )

    async def _run() -> tuple[GroupInfo, int, int]:
        client = make_client(settings)
        await client.start(phone=settings.phone)
        try:
            return await sync_group(client, settings, since=since, progress=progress)
        finally:
            await client.disconnect()

    return asyncio.run(_run())
