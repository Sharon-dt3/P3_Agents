"""
Escalation store (CHN-23): the one write path into the escalations table.

Mirrors nudges_repo.py's own split almost exactly. record() is an
upsert on idempotency_key, so re-attempting the same not-yet-sent
escalation (a rerun before it has been approved) replaces its
bookkeeping row in place rather than duplicating it, and mark_sent()
is the one write path into sent_at, called once and only once an
escalation has actually gone out through SPN-09's guarded_send().

has_ever_been_escalated() is the CHN-23 counterpart to
NudgeStore.has_ever_been_nudged() -- scoped per person, not per
channel, because an escalation is a private message about one
individual, not a channel post. A person where this is still False
gets their next escalation left pending for a human to approve; once
it flips True, a later escalation to the owner about that same person
auto-approves. There is deliberately no per-day counter here (nudges
have sent_count_for_day() for their per-day cap): an escalation's own
cap is structural, not counted -- p1.escalations.escalation_job keys
each escalation's idempotency_key on (channel_id, member_id,
streak_start_date), so at most one escalation is ever sent per
unbroken missed-day streak, however long that streak grows, and a
fresh streak (after the person breaks it by posting a real update)
gets its own key and can escalate again.
"""

from __future__ import annotations

from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class EscalationStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._db_path = db_path

    def record(
        self,
        *,
        channel_id: str,
        member_id: str,
        streak_start_date: str,
        date: str,
        idempotency_key: str,
        proposal_id: str,
    ) -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO escalations
                    (channel_id, member_id, streak_start_date, date, proposal_id, idempotency_key)
                VALUES (:channel_id, :member_id, :streak_start_date, :date, :proposal_id, :idempotency_key)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    proposal_id = excluded.proposal_id
                """,
                {
                    "channel_id": channel_id,
                    "member_id": member_id,
                    "streak_start_date": streak_start_date,
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
                "SELECT channel_id, member_id, streak_start_date, date, proposal_id, sent_at, idempotency_key "
                "FROM escalations WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row is not None else None

    def mark_sent(self, *, idempotency_key: str, sent_at: str) -> None:
        """Idempotent to call more than once -- the one thing that must
        never happen twice is the send itself (guarded_send()'s job),
        not this bookkeeping call."""
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                "UPDATE escalations SET sent_at = ? WHERE idempotency_key = ?",
                (sent_at, idempotency_key),
            )
            conn.commit()
        finally:
            conn.close()

    def has_ever_been_escalated(self, channel_id: str, member_id: str) -> bool:
        """True iff this person has an escalation row with a non-null
        sent_at in this channel, for ANY streak -- not just the current
        one. This is the question CHN-23's first-escalation-requires-
        approval rule is built on, scoped per person rather than per
        channel, the same way has_ever_been_nudged() is."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT 1 FROM escalations WHERE channel_id = ? AND member_id = ? AND sent_at IS NOT NULL LIMIT 1",
                (channel_id, member_id),
            ).fetchone()
        finally:
            conn.close()
        return row is not None
