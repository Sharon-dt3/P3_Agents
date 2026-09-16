"""
Message store (CHN-05): edit-safe upsert of TeamsMessage rows into the
messages table. A message's identity fields (channel_id, author_id,
thread_root_id, posted_at, is_bot, is_system) are set once, on first
insert, and never touched again -- posted_at in particular must never
be overwritten by a later edit, per the ingestion acceptance criteria.
Only the genuinely mutable fields (edited_at, deleted_at, is_deleted,
body, permalink) are refreshed on a re-seen message.
"""

from __future__ import annotations

from pathlib import Path

from p1.adapters.teams_reader import TeamsMessage
from p1.storage.db import DEFAULT_DB_PATH, get_connection


class MessageStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = db_path

    def upsert_messages(self, messages: list[TeamsMessage]) -> None:
        if not messages:
            return
        conn = get_connection(self._db_path)
        try:
            for message in messages:
                conn.execute(
                    """
                    INSERT INTO messages (
                        id, channel_id, author_id, thread_root_id, posted_at,
                        edited_at, deleted_at, is_deleted, is_bot, is_system,
                        body_raw, body_normalized, permalink
                    ) VALUES (
                        :id, :channel_id, :author_id, :thread_root_id, :posted_at,
                        :edited_at, :deleted_at, :is_deleted, :is_bot, :is_system,
                        :body_raw, :body_normalized, :permalink
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        edited_at = excluded.edited_at,
                        deleted_at = excluded.deleted_at,
                        is_deleted = excluded.is_deleted,
                        body_raw = excluded.body_raw,
                        body_normalized = excluded.body_normalized,
                        permalink = excluded.permalink
                    """,
                    {
                        "id": message.id,
                        "channel_id": message.channel_id,
                        "author_id": message.author_id,
                        "thread_root_id": message.thread_root_id,
                        "posted_at": message.posted_at,
                        "edited_at": message.edited_at,
                        "deleted_at": message.deleted_at,
                        "is_deleted": int(message.is_deleted),
                        "is_bot": int(message.is_bot),
                        "is_system": int(message.is_system),
                        "body_raw": message.body,
                        "body_normalized": _normalize(message.body),
                        "permalink": message.permalink,
                    },
                )
            conn.commit()
        finally:
            conn.close()


def _normalize(body: str) -> str:
    """Minimal text normalisation for FTS search -- strips surrounding
    whitespace. Richer HTML-to-text cleanup belongs to whichever
    capability first needs to read this field for classification
    (CHN-08/09), not to ingestion itself."""
    return body.strip()
