"""
Focused tests for NudgeStore -- mirrors test_digests_repo.py's own
structure and rationale, since NudgeStore is deliberately built the
same way DigestStore is (see nudges_repo.py's own module docstring),
just scoped one level narrower: per person, not per channel.
"""

from __future__ import annotations

import pytest

from p1.storage.db import get_connection, init_db
from p1.storage.nudges_repo import NudgeStore


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    try:
        conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'C1', 1)")
        for member_id in ("alice", "bob"):
            conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()
    return path


def test_has_ever_been_nudged_is_false_before_any_send(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")

    assert store.has_ever_been_nudged("c1", "alice") is False


def test_mark_sent_sets_sent_at(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")

    store.mark_sent(idempotency_key="c1:alice:2026-06-01:1", sent_at="2026-06-01T09:05:00+00:00")

    row = store.get_by_idempotency_key("c1:alice:2026-06-01:1")
    assert row["sent_at"] == "2026-06-01T09:05:00+00:00"


def test_has_ever_been_nudged_is_true_after_any_date_is_marked_sent(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")
    store.record(channel_id="c1", member_id="alice", date="2026-06-08", idempotency_key="c1:alice:2026-06-08:1", proposal_id="p2")

    store.mark_sent(idempotency_key="c1:alice:2026-06-01:1", sent_at="2026-06-01T09:05:00+00:00")

    # Only the 2026-06-01 nudge was ever marked sent, but
    # has_ever_been_nudged asks across ALL dates, not just the latest.
    assert store.has_ever_been_nudged("c1", "alice") is True


def test_has_ever_been_nudged_is_scoped_per_person_not_per_channel(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")
    store.mark_sent(idempotency_key="c1:alice:2026-06-01:1", sent_at="2026-06-01T09:05:00+00:00")
    store.record(channel_id="c1", member_id="bob", date="2026-06-01", idempotency_key="c1:bob:2026-06-01:1", proposal_id="p2")

    assert store.has_ever_been_nudged("c1", "alice") is True
    assert store.has_ever_been_nudged("c1", "bob") is False


def test_sent_count_for_day_only_counts_rows_marked_sent(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:2", proposal_id="p2")
    store.mark_sent(idempotency_key="c1:alice:2026-06-01:1", sent_at="2026-06-01T09:05:00+00:00")
    # The second nudge attempt today was recorded (e.g. proposed) but
    # never actually sent -- it must not count toward the cap.

    assert store.sent_count_for_day("c1", "alice", "2026-06-01") == 1


def test_sent_count_for_day_is_scoped_to_the_given_date(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")
    store.mark_sent(idempotency_key="c1:alice:2026-06-01:1", sent_at="2026-06-01T09:05:00+00:00")

    assert store.sent_count_for_day("c1", "alice", "2026-06-02") == 0


def test_record_upserts_by_idempotency_key(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1-replaced")

    row = store.get_by_idempotency_key("c1:alice:2026-06-01:1")
    assert row["proposal_id"] == "p1-replaced"


def test_mark_sent_is_safe_to_call_more_than_once(db_path):
    store = NudgeStore(db_path)
    store.record(channel_id="c1", member_id="alice", date="2026-06-01", idempotency_key="c1:alice:2026-06-01:1", proposal_id="p1")

    store.mark_sent(idempotency_key="c1:alice:2026-06-01:1", sent_at="2026-06-01T09:05:00+00:00")
    store.mark_sent(idempotency_key="c1:alice:2026-06-01:1", sent_at="2026-06-01T09:05:00+00:00")

    row = store.get_by_idempotency_key("c1:alice:2026-06-01:1")
    assert row["sent_at"] == "2026-06-01T09:05:00+00:00"
