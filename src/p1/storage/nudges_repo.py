"""
Nudge store (CHN-21): the one write path into the nudges table.

Mirrors digests_repo.py's own split almost exactly, and for the same
reason: record() is an upsert on idempotency_key, so re-attempting the
same not-yet-sent nudge (a rerun before it has been approved) replaces
its bookkeeping row in place rather than duplicating it, and
mark_sent() is the one write path into sent_at, called once and only
once a nudge has actually gone out through SPN-09's guarded_send().

has_ever_been_nudged() and sent_count_for_day() are the two questions
p1.nudges.nudge_job builds its whole safety story on:

  - has_ever_been_nudged(channel_id, member_id) -- has this person ever
    been successfully nudged in this channel, on any date -- is the
    CHN-21 counterpart to DigestStore.has_ever_published(channel_id),
    just scoped one level narrower (per person, not per channel,
    because a nudge is a message to one individual, not a channel
    post). A person where this is still False gets their next nudge
    left pending for a human to approve; once it flips True, every
    later nudge to that same person auto-approves.

  - sent_count_for_day(channel_id, member_id, date) -- how many nudges
    this person has actually RECEIVED today, in this channel -- is the
    hard per-person-per-day cap check. It counts only rows with a
    non-null sent_at, deliberately: a pending or rejected nudge attempt
    was never delivered, so it must never count against the cap the
    same way an unsent proposal never counts as "already published" in
    CHN-17/18.
"""

from __future__ import annotations

from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class NudgeStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    def record(
        self,
        *,
        channel_id: str,
        member_id: str,
        date: str,
        idempotency_key: str,
        proposal_id: str,
    ) -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO nudges (channel_id, member_id, date, proposal_id, idempotency_key)
                VALUES (:channel_id, :member_id, :date, :proposal_id, :idempotency_key)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    proposal_id = excluded.proposal_id
                """,
                {
                    "channel_id": channel_id,
                    "member_id": member_id,
                    "date": date,
                    "proposal_id": proposal_id,
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
                "SELECT channel_id, member_id, date, proposal_id, sent_at, idempotency_key "
                "FROM nudges WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row is not None else None

    def mark_sent(self, *, idempotency_key: str, sent_at: str) -> None:
        """Idempotent to call more than once, same rationale as
        DigestStore.mark_published(): the one thing that must never
        happen twice is the send itself (guarded_send()'s job), not
        this bookkeeping call."""
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                "UPDATE nudges SET sent_at = ? WHERE idempotency_key = ?",
                (sent_at, idempotency_key),
            )
            conn.commit()
        finally:
            conn.close()

    def sent_count_for_day(self, channel_id: str, member_id: str, date: str) -> int:
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM nudges "
                "WHERE channel_id = ? AND member_id = ? AND date = ? AND sent_at IS NOT NULL",
                (channel_id, member_id, date),
            ).fetchone()
        finally:
            conn.close()
        return row["n"]

    def has_ever_been_nudged(self, channel_id: str, member_id: str) -> bool:
        """True iff this person has a nudge row with a non-null sent_at
        in this channel, for ANY date -- not just today's. This is the
        question CHN-21's first-nudge-requires-approval rule is built
        on, scoped per person rather than per channel."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM nudges WHERE channel_id = ? AND member_id = ? AND sent_at IS NOT NULL LIMIT 1",
                (channel_id, member_id),
            ).fetchone()
        finally:
            conn.close()
        return row is not None
