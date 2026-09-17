"""
Focused tests for the two methods CHN-17 adds to DigestStore --
mark_published() and has_ever_published() -- kept separate from
tests/unit/test_daily_job.py (which exercises both indirectly through
the full job) so a regression in this store's own logic points here
first.
"""

from __future__ import annotations

import pytest

from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    try:
        conn.execute(
            "INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'C1', 1)"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_has_ever_published_is_false_before_any_publish(db_path):
    store = DigestStore(db_path)
    store.record(channel_id="c1", date="2026-06-01", type="daily", content="day one", idempotency_key="c1:2026-06-01:daily")

    assert store.has_ever_published("c1") is False


def test_mark_published_sets_published_at(db_path):
    store = DigestStore(db_path)
    store.record(channel_id="c1", date="2026-06-01", type="daily", content="day one", idempotency_key="c1:2026-06-01:daily")

    store.mark_published(idempotency_key="c1:2026-06-01:daily", published_at="2026-06-01T09:05:00+00:00")

    row = store.get_by_idempotency_key("c1:2026-06-01:daily")
    assert row["published_at"] == "2026-06-01T09:05:00+00:00"


def test_has_ever_published_is_true_after_any_date_is_marked_published(db_path):
    store = DigestStore(db_path)
    store.record(channel_id="c1", date="2026-06-01", type="daily", content="day one", idempotency_key="c1:2026-06-01:daily")
    store.record(channel_id="c1", date="2026-06-02", type="daily", content="day two", idempotency_key="c1:2026-06-02:daily")

    store.mark_published(idempotency_key="c1:2026-06-01:daily", published_at="2026-06-01T09:05:00+00:00")

    # Only day 1 was ever marked published, but has_ever_published asks
    # about the channel across ALL dates, not just the most recent one.
    assert store.has_ever_published("c1") is True


def test_has_ever_published_is_false_for_a_different_unpublished_channel(db_path):
    conn = get_connection(db_path)
    try:
        conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c2', 'C2', 1)")
        conn.commit()
    finally:
        conn.close()
    store = DigestStore(db_path)
    store.record(channel_id="c1", date="2026-06-01", type="daily", content="day one", idempotency_key="c1:2026-06-01:daily")
    store.mark_published(idempotency_key="c1:2026-06-01:daily", published_at="2026-06-01T09:05:00+00:00")
    store.record(channel_id="c2", date="2026-06-01", type="daily", content="c2 day one", idempotency_key="c2:2026-06-01:daily")

    assert store.has_ever_published("c2") is False


def test_mark_published_is_safe_to_call_more_than_once(db_path):
    store = DigestStore(db_path)
    store.record(channel_id="c1", date="2026-06-01", type="daily", content="day one", idempotency_key="c1:2026-06-01:daily")

    store.mark_published(idempotency_key="c1:2026-06-01:daily", published_at="2026-06-01T09:05:00+00:00")
    store.mark_published(idempotency_key="c1:2026-06-01:daily", published_at="2026-06-01T09:05:00+00:00")

    row = store.get_by_idempotency_key("c1:2026-06-01:daily")
    assert row["published_at"] == "2026-06-01T09:05:00+00:00"
