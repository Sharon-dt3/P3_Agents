"""
Digest store (CHN-13): the one write path into the digests table for a
generated summary's rendered content.

record() is an upsert keyed on idempotency_key, so regenerating a day's
digest before it has been published (CHN-17's job, not this one)
replaces its content in place rather than duplicating a row --
consistent with every other store in this codebase (MessageStore,
ClassificationStore, ParticipationStore all upsert-on-reprocess the same
way). published_at was deliberately left untouched by CHN-13: publishing
a digest is CHN-17's concern, not this module's -- CHN-17 is what now
adds the two methods that touch it.

mark_published() (CHN-17) is the one write path into published_at --
called once a digest has actually been sent, never before. It records
*when*, not just *that*, a fixed idempotency_key was published; it does
not decide whether sending was allowed in the first place (SPN-09's
write guard already refused the send if it wasn't approved, and this
method only ever runs after guarded_send() returns successfully).

has_ever_published() (CHN-17) answers a different question from
get_by_idempotency_key(): not "has *this date's* digest been published"
but "has this channel published on *any* date before" -- the fact
run_daily_digest_job's first-publish-requires-approval rule is actually
built on. A channel's very first due day is the one where this returns
False; every day after, once that first send has gone out, it returns
True and the job auto-approves without asking a human again.
"""

from __future__ import annotations

from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class DigestStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = db_path

    def record(
        self,
        *,
        channel_id: str,
        date: str,
        type: str,
        content: str,
        idempotency_key: str,
    ) -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO digests (channel_id, date, type, content, idempotency_key)
                VALUES (:channel_id, :date, :type, :content, :idempotency_key)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    content = excluded.content
                """,
                {
                    "channel_id": channel_id,
                    "date": date,
                    "type": type,
                    "content": content,
                    "idempotency_key": idempotency_key,
                },
            )
            conn.commit()
        finally:
            conn.close()

    def get_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT channel_id, date, type, content, published_at, idempotency_key "
                "FROM digests WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row is not None else None

    def mark_published(self, *, idempotency_key: str, published_at: str) -> None:
        """Records that the digest at this idempotency_key has been
        sent. Idempotent to call more than once (e.g. a retried
        publish job) -- it always sets published_at to the given
        value rather than refusing on an already-set column, since the
        one thing that must never happen twice is the send itself
        (SPN-09's write guard's job), not this bookkeeping call."""
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                "UPDATE digests SET published_at = ? WHERE idempotency_key = ?",
                (published_at, idempotency_key),
            )
            conn.commit()
        finally:
            conn.close()

    def has_ever_published(self, channel_id: str) -> bool:
        """True iff this channel has a digest row with a non-null
        published_at for ANY date -- not just today's. This is the
        question CHN-17's first-publish-requires-approval rule is
        built on: a channel where this is still False has never had a
        digest sent, so its next due day must wait for a human; once
        this flips True it stays True, and every later day runs
        unattended."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM digests WHERE channel_id = ? AND published_at IS NOT NULL LIMIT 1",
                (channel_id,),
            ).fetchone()
        finally:
            conn.close()
        return row is not None

    def has_ever_published_type(self, channel_id: str, type: str) -> bool:
        """Like has_ever_published(), but scoped to one digest type
        ('daily' or 'weekly'). The weekly roll-up is a different kind of
        message from the daily digest, so the first one ever sent to a
        channel must wait for a human even though that channel has long
        since had daily digests published -- "no channel ever receives an
        unexpected bot post" applies per kind of post, not once per
        channel."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM digests WHERE channel_id = ? AND type = ? AND published_at IS NOT NULL LIMIT 1",
                (channel_id, type),
            ).fetchone()
        finally:
            conn.close()
        return row is not None
