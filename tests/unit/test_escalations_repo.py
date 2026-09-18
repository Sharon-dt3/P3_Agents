from __future__ import annotations

from p1.storage.db import get_connection, init_db
from p1.storage.escalations_repo import EscalationStore


def _seed_channel_and_member(db_path, channel_id="c1", member_id="bob"):
    # members is a single global roster (a person can be on more than one
    # channel), so re-seeding the same member_id for a second channel must
    # not re-insert the row.
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'C', 1)", (channel_id,)
        )
        conn.execute("INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()


def test_record_then_get_by_idempotency_key_round_trips(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_channel_and_member(db_path)
    store = EscalationStore(db_path)

    store.record(
        channel_id="c1", member_id="bob", streak_start_date="2026-06-01", date="2026-06-03",
        idempotency_key="c1:bob:2026-06-01", proposal_id="p1",
    )

    row = store.get_by_idempotency_key("c1:bob:2026-06-01")
    assert row["channel_id"] == "c1"
    assert row["member_id"] == "bob"
    assert row["streak_start_date"] == "2026-06-01"
    assert row["date"] == "2026-06-03"
    assert row["proposal_id"] == "p1"
    assert row["sent_at"] is None


def test_get_by_idempotency_key_returns_none_when_absent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    assert EscalationStore(db_path).get_by_idempotency_key("nope") is None


def test_record_is_an_upsert_on_idempotency_key(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_channel_and_member(db_path)
    store = EscalationStore(db_path)

    store.record(
        channel_id="c1", member_id="bob", streak_start_date="2026-06-01", date="2026-06-03",
        idempotency_key="c1:bob:2026-06-01", proposal_id="p1",
    )
    store.record(
        channel_id="c1", member_id="bob", streak_start_date="2026-06-01", date="2026-06-04",
        idempotency_key="c1:bob:2026-06-01", proposal_id="p2",
    )

    row = store.get_by_idempotency_key("c1:bob:2026-06-01")
    assert row["proposal_id"] == "p2"

    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM escalations").fetchone()["n"]
    finally:
        conn.close()
    assert count == 1


def test_mark_sent_sets_sent_at(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_channel_and_member(db_path)
    store = EscalationStore(db_path)
    store.record(
        channel_id="c1", member_id="bob", streak_start_date="2026-06-01", date="2026-06-03",
        idempotency_key="c1:bob:2026-06-01", proposal_id="p1",
    )

    store.mark_sent(idempotency_key="c1:bob:2026-06-01", sent_at="2026-06-03T09:00:00+00:00")

    row = store.get_by_idempotency_key("c1:bob:2026-06-01")
    assert row["sent_at"] == "2026-06-03T09:00:00+00:00"


def test_mark_sent_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_channel_and_member(db_path)
    store = EscalationStore(db_path)
    store.record(
        channel_id="c1", member_id="bob", streak_start_date="2026-06-01", date="2026-06-03",
        idempotency_key="c1:bob:2026-06-01", proposal_id="p1",
    )

    store.mark_sent(idempotency_key="c1:bob:2026-06-01", sent_at="2026-06-03T09:00:00+00:00")
    store.mark_sent(idempotency_key="c1:bob:2026-06-01", sent_at="2026-06-03T09:00:00+00:00")

    row = store.get_by_idempotency_key("c1:bob:2026-06-01")
    assert row["sent_at"] == "2026-06-03T09:00:00+00:00"


def test_has_ever_been_escalated_is_false_until_a_sent_row_exists(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_channel_and_member(db_path)
    store = EscalationStore(db_path)
    store.record(
        channel_id="c1", member_id="bob", streak_start_date="2026-06-01", date="2026-06-03",
        idempotency_key="c1:bob:2026-06-01", proposal_id="p1",
    )

    assert store.has_ever_been_escalated("c1", "bob") is False

    store.mark_sent(idempotency_key="c1:bob:2026-06-01", sent_at="2026-06-03T09:00:00+00:00")

    assert store.has_ever_been_escalated("c1", "bob") is True


def test_has_ever_been_escalated_is_scoped_per_channel_and_member(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    _seed_channel_and_member(db_path, channel_id="c1", member_id="bob")
    _seed_channel_and_member(db_path, channel_id="c2", member_id="bob")
    store = EscalationStore(db_path)
    store.record(
        channel_id="c1", member_id="bob", streak_start_date="2026-06-01", date="2026-06-03",
        idempotency_key="c1:bob:2026-06-01", proposal_id="p1",
    )
    store.mark_sent(idempotency_key="c1:bob:2026-06-01", sent_at="2026-06-03T09:00:00+00:00")

    assert store.has_ever_been_escalated("c1", "bob") is True
    assert store.has_ever_been_escalated("c2", "bob") is False
