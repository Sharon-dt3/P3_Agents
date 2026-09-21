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
                self._ensure_member_exists(conn, message.author_id)
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

    def list_root_message_ids(self, channel_id: str, since: str | None = None) -> list[str]:
        """IDs of every non-deleted root message (thread_root_id IS NULL)
        this channel has in `messages` -- the exact set a caller needs to
        then fetch each root's replies via TeamsReader.list_replies(),
        since Graph's own delta endpoint never returns replies at all
        (see ingestion.sync.sync_channel_replies's own docstring and
        DECISION_LOG.md's thread-replies-ingestion entry).

        since, when given, is an ISO-8601 posted_at lower bound -- a
        simple, explicit way to bound this to recently-active roots
        instead of paying to re-check every reply-fetch call against
        this channel's entire history on every tick, once a channel has
        been running long enough for that to matter. Callers that don't
        need bounding (a small/test channel, or a deliberate full
        resync) simply omit it."""
        conn = get_connection(self._db_path)
        try:
            if since is not None:
                rows = conn.execute(
                    """
                    SELECT id FROM messages
                    WHERE channel_id = ? AND thread_root_id IS NULL
                      AND is_deleted = 0 AND posted_at >= ?
                    ORDER BY posted_at
                    """,
                    (channel_id, since),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id FROM messages
                    WHERE channel_id = ? AND thread_root_id IS NULL AND is_deleted = 0
                    ORDER BY posted_at
                    """,
                    (channel_id,),
                ).fetchall()
        finally:
            conn.close()
        return [row["id"] for row in rows]

    @staticmethod
    def _ensure_member_exists(conn, author_id: str | None) -> None:
        """messages.author_id is a foreign key into members(id)
        (PRAGMA foreign_keys = ON, see p1.storage.db) -- so ingesting a
        real message from anyone not already known to this database
        would otherwise crash the whole sync outright with a foreign
        key violation, not just fail to show a nice display name.

        This was a real, previously-open gap (see DECISION_LOG.md and
        README.md's CHN-31 entry): the only thing populating `members`
        was scripts/run_daily.py, scripts/run_walkthrough.py, and
        p1.eval.chn12_cases each separately pre-inserting rows from
        their own committed fixture data before calling into ingestion
        -- fine for a demo that only ever ingests fixture authors, but
        nothing at all did this for a real Graph-backed sync, where the
        author_ids ingestion actually encounters are not known ahead of
        time.

        Fixing it here, centrally, in the one place every reader's
        messages actually pass through (mock, Graph, or fixtures
        alike), means no caller needs to pre-seed anything, ever again,
        regardless of which TeamsReader produced the message.
        `TeamsMessage` doesn't carry a display name (Graph's own delta
        message payload only ever gives a sender's id reliably -- see
        GraphTeamsReader._parse_message), so a never-before-seen
        author_id is registered using itself as a placeholder
        display_name, exactly matching the fallback every existing
        fixture-seeding call site above already used
        (`INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)`
        with author_id passed for both) -- this generalizes that same,
        already-proven pattern rather than inventing a new one.
        A real display name can be filled in later (e.g. once CHN-01's
        list_channel_members() -- already written, just never wired
        into ingestion -- is actually called) without this path ever
        needing to change: INSERT OR IGNORE never overwrites a row a
        richer sync already populated."""
        if author_id is None:
            return
        conn.execute(
            "INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)",
            (author_id, author_id),
        )


def _normalize(body: str) -> str:
    """Minimal text normalisation for FTS search -- strips surrounding
    whitespace. Richer HTML-to-text cleanup belongs to whichever
    capability first needs to read this field for classification
    (CHN-08/09), not to ingestion itself."""
    return body.strip()
