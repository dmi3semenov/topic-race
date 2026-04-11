from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import AsyncIterator

from telethon import TelegramClient
from telethon.tl.functions.messages import GetForumTopicsRequest
from telethon.tl.types import Channel, ForumTopic, Message

from .config import Settings
from .storage import MessageRow, TopicRow

log = logging.getLogger(__name__)


@dataclass
class GroupInfo:
    chat_id: int
    title: str
    is_forum: bool


def make_client(settings: Settings) -> TelegramClient:
    return TelegramClient(
        str(settings.session_path),
        settings.api_id,
        settings.api_hash,
    )


async def find_group(client: TelegramClient, name: str) -> GroupInfo:
    async for dialog in client.iter_dialogs():
        entity = dialog.entity
        if not isinstance(entity, Channel):
            continue
        if (dialog.name or "").strip().lower() == name.strip().lower():
            return GroupInfo(
                chat_id=entity.id,
                title=dialog.name,
                is_forum=bool(getattr(entity, "forum", False)),
            )
    raise LookupError(f"Group {name!r} not found in dialogs")


async def fetch_topics(client: TelegramClient, group: GroupInfo) -> list[TopicRow]:
    entity = await client.get_entity(group.chat_id)
    result = await client(
        GetForumTopicsRequest(
            peer=entity,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=200,
        )
    )
    topics: list[TopicRow] = []
    for t in result.topics:
        if not isinstance(t, ForumTopic):
            continue
        emoji = None
        if getattr(t, "icon_emoji_id", None):
            emoji = None
        topics.append(
            TopicRow(
                chat_id=group.chat_id,
                topic_id=t.id,
                title=t.title,
                icon_emoji=emoji,
            )
        )
    return topics


async def fetch_topic_messages(
    client: TelegramClient,
    group: GroupInfo,
    topic: TopicRow,
    since: datetime | None = None,
) -> AsyncIterator[MessageRow]:
    """Fetch all messages of a forum topic. Dedup is handled by INSERT OR IGNORE
    in storage. Deliberately does NOT use `min_id` — it's unsafe when prior sync
    used a date window, and would silently skip older backfill messages.
    """
    entity = await client.get_entity(group.chat_id)
    async for msg in client.iter_messages(entity, reply_to=topic.topic_id):
        if not isinstance(msg, Message):
            continue
        msg_date = msg.date
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        if since and msg_date < since:
            continue
        from_id = None
        if msg.from_id and hasattr(msg.from_id, "user_id"):
            from_id = msg.from_id.user_id
        elif msg.sender_id:
            from_id = int(msg.sender_id)
        grouped_id = getattr(msg, "grouped_id", None)
        yield MessageRow(
            chat_id=group.chat_id,
            topic_id=topic.topic_id,
            message_id=msg.id,
            date=msg_date,
            from_id=from_id,
            grouped_id=int(grouped_id) if grouped_id else None,
        )
