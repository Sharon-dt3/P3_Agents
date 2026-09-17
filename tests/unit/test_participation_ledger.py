from datetime import date, time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.participation.ledger import (
    EXCLUDED,
    NO_MESSAGE,
    POSTED_NO_UPDATE,
    NonWorkingDayError,
    build_and_persist_ledger,
    build_ledger,
)
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

TZ = "Asia/Colombo"
DAY = date(2025, 6, 2)  # a Monday


def make_config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "c1",
        "display_name": "Channel One",
        "allowlisted": True,
        "roster": ["alice", "bob", "carol", "dave"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": TZ,
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "length_floor": 10,
        "count_thread_replies": True,
        "ignore_bots": True,
        "daily_digest_time": time(11, 30),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
        "exceptions": [{"member_id": "dave", "reason": "On leave"}],
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def _message(**overrides) -> TeamsMessage:
    defaults = {
        "id": "m1",
        "channel_id": "c1",
        "author_id": "alice",
        "posted_at": "2025-06-02T09:30:00+05:30",
        "body": "Finished the thing, running the tests now.",
    }
    defaults.update(overrides)
    return TeamsMessage(**defaults)


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'Channel One', 1)")
    for member_id in ("alice", "bob", "carol", "dave"):
        conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
    conn.commit()
    conn.close()
    return path


def test_contributor_never_appears_in_the_ledger(db_path):
    message = _message(id="m1", author_id="alice")
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id="m1", label="update", method="model", confidence=0.9)

    records = build_ledger("c1", DAY, make_config(), db_path=db_path)
    assert "alice" not in {r.member_id for r in records}


def test_member_with_zero_messages_is_no_message(db_path):
    records = build_ledger("c1", DAY, make_config(), db_path=db_path)
    by_member = {r.member_id: r for r in records}
    assert by_member["bob"].state == NO_MESSAGE
    assert by_member["bob"].evidence_message_ids == ()


def test_member_with_only_chatter_is_posted_no_update(db_path):
    message = _message(id="m2", author_id="bob", body="Thanks!")
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id="m2", label="chatter", method="model", confidence=0.9)

    records = build_ledger("c1", DAY, make_config(), db_path=db_path)
    by_member = {r.member_id: r for r in records}
    assert by_member["bob"].state == POSTED_NO_UPDATE
    assert by_member["bob"].evidence_message_ids == ("m2",)


def test_deleted_only_message_reverts_to_no_message(db_path):
    """CHN-07's DIFF-DEL-0x: a retracted message is not evidence of
    having posted -- the day must revert to a genuine no_message day,
    not a fabricated posted_no_update."""
    message = _message(id="m3", author_id="carol", is_deleted=True, body="Started work on the index.")
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id="m3", label="noise", method="rule", rule_name="deleted_message")

    records = build_ledger("c1", DAY, make_config(), db_path=db_path)
    by_member = {r.member_id: r for r in records}
    assert by_member["carol"].state == NO_MESSAGE
    assert by_member["carol"].evidence_message_ids == ()


def test_on_leave_member_with_no_messages_is_excluded(db_path):
    records = build_ledger("c1", DAY, make_config(), db_path=db_path)
    by_member = {r.member_id: r for r in records}
    assert by_member["dave"].state == EXCLUDED


def test_on_leave_member_who_actually_contributes_is_not_in_the_ledger_at_all(db_path):
    """A real update beats exception-list membership: exceptions only
    ever excuse a non-responder, they never hide someone who genuinely
    did respond that day."""
    message = _message(id="m4", author_id="dave", body="Finished the release notes.")
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id="m4", label="update", method="model", confidence=0.9)

    records = build_ledger("c1", DAY, make_config(), db_path=db_path)
    assert "dave" not in {r.member_id for r in records}


def test_non_working_day_raises(db_path):
    saturday = date(2025, 6, 7)
    with pytest.raises(NonWorkingDayError):
        build_ledger("c1", saturday, make_config(), db_path=db_path)


def test_ledger_is_sorted_by_member_id(db_path):
    records = build_ledger("c1", DAY, make_config(), db_path=db_path)
    member_ids = [r.member_id for r in records]
    assert member_ids == sorted(member_ids)


def test_build_and_persist_ledger_writes_the_participation_table(db_path):
    build_and_persist_ledger("c1", DAY, make_config(), db_path=db_path)

    conn = get_connection(db_path)
    try:
        rows = {
            row["member_id"]: row["state"]
            for row in conn.execute(
                "SELECT member_id, state FROM participation WHERE channel_id = 'c1' AND date = ?",
                (DAY.isoformat(),),
            )
        }
    finally:
        conn.close()

    assert rows["dave"] == EXCLUDED
    assert rows["bob"] == NO_MESSAGE


def test_rerunning_build_and_persist_ledger_replaces_rather_than_duplicates(db_path):
    build_and_persist_ledger("c1", DAY, make_config(), db_path=db_path)
    build_and_persist_ledger("c1", DAY, make_config(), db_path=db_path)

    conn = get_connection(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM participation WHERE channel_id = 'c1' AND date = ? AND member_id = 'dave'",
            (DAY.isoformat(),),
        ).fetchone()["n"]
    finally:
        conn.close()

    assert count == 1
