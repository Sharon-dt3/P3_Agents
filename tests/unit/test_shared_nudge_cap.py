"""One person is never chased by two agents on the same day: P1's side of the estate-wide nudge cap.

P1's own cap (nudge_cap_per_day) is per person per CHANNEL and can see only P1's own ledger. This opt-in cap is per
PERSON across every channel and across the other agents' ledgers too (P2 keeps a `nudges` table of the same shape):
set P1_SHARED_NUDGE_CAP_PER_DAY and list the other agents' databases in P1_PEER_NUDGE_LEDGERS. Left unset, P1
behaves exactly as it always has. Peer ledgers are only ever read; if one is configured and cannot be read, nobody
is nudged (not knowing whether someone was already chased is a reason to wait, not to send).
"""

from __future__ import annotations

import sqlite3
from datetime import date, time

import pytest

from p1.approval.proposals import ProposalStore
from p1.config.schema import ChannelConfig
from p1.nudges.nudge_job import CAP_REACHED, CAP_UNAVAILABLE, SENT, run_nudge_job
from p1.nudges.shared_cap import (
    SharedCapUnavailableError,
    SharedNudgeCap,
    shared_cap_from_environment,
)
from p1.participation.ledger import NO_MESSAGE, ParticipationRecord
from p1.storage.db import get_connection, init_db
from p1.storage.nudges_repo import NudgeStore

DAY = date(2026, 6, 1)  # a Monday
CAP_ENV, PEERS_ENV = "P1_SHARED_NUDGE_CAP_PER_DAY", "P1_PEER_NUDGE_LEDGERS"


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "nudge-channel", "display_name": "Nudge Test Channel", "roster": ["alice", "bob"],
        "update_window_start": time(9, 0), "update_window_end": time(11, 0), "timezone": "UTC",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "non_working_dates": [], "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri", "weekly_digest_time": time(16, 0), "channel_owner_id": "alice", "exceptions": [],
        "nudge_enabled": True, "nudge_cap_per_day": 1,
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "p1.db")
    init_db(path)
    conn = get_connection(path)
    try:
        for channel in ("nudge-channel", "other-channel"):
            conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'C', 1)", (channel,))
        conn.execute("INSERT INTO members (id, display_name) VALUES ('alice', 'Alice Anders')")
        conn.execute("INSERT INTO members (id, display_name) VALUES ('bob', 'Bob Brown')")
        conn.commit()
    finally:
        conn.close()
    return path


def _peer(tmp_path, nudges=(), people=(), name_table="assignees"):
    """Another agent's database: a `nudges` table of the shared shape, and a table naming its people."""
    path = tmp_path / "peer.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE nudges (id INTEGER PRIMARY KEY AUTOINCREMENT, member_id TEXT NOT NULL, date TEXT NOT NULL, "
                 "commitment_id INTEGER, proposal_id TEXT, sent_at TEXT, idempotency_key TEXT NOT NULL UNIQUE)")
    conn.execute(f"CREATE TABLE {name_table} (id TEXT PRIMARY KEY, display_name TEXT)")
    conn.executemany(f"INSERT INTO {name_table} (id, display_name) VALUES (?, ?)", people)
    for i, (member, day, sent) in enumerate(nudges):
        conn.execute("INSERT INTO nudges (member_id, date, sent_at, idempotency_key) VALUES (?, ?, ?, ?)", (member, day, sent, f"k{i}"))
    conn.commit()
    conn.close()
    return path


class _Recorder:
    def __init__(self):
        self.calls = []

    def post_direct_message(self, member_id, content):
        self.calls.append((member_id, content))
        return {"ok": True}


def _bob_is_a_non_responder():
    return [ParticipationRecord(channel_id="nudge-channel", member_id="bob", date=DAY.isoformat(), state=NO_MESSAGE, evidence_message_ids=())]


def _run(db_path, config=None, publisher=None):
    config = config or _config()
    return run_nudge_job(config.channel_id, config, publisher or _Recorder(), day=DAY, db_path=db_path, ledger_records=_bob_is_a_non_responder())


def _bob(results):
    (result,) = [r for r in results if r.member_id == "bob"]
    return result


def _proposals(db_path):
    conn = get_connection(db_path)
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM proposals WHERE idempotency_key LIKE 'nudge-channel:bob:%'").fetchone()["n"]
    finally:
        conn.close()


def _make_bob_previously_nudged(db_path, config, publisher):
    """A person who has been nudged before, so today's nudge auto-approves and sends (the steady state)."""
    NudgeStore(db_path).record(channel_id=config.channel_id, member_id="bob", date="2026-05-25", idempotency_key="old", proposal_id="p-old")
    NudgeStore(db_path).mark_sent(idempotency_key="old", sent_at="2026-05-25T09:00:00+00:00")


# --- off by default: P1 behaves as it always has -----------------------------------------------------------------------------------


def test_with_nothing_set_a_peers_nudge_is_ignored_and_p1_nudges_as_before(db_path, tmp_path, monkeypatch):
    monkeypatch.delenv(CAP_ENV, raising=False)
    monkeypatch.setenv(PEERS_ENV, str(_peer(tmp_path, [("bob", DAY.isoformat(), "2026-06-01T08:00:00+00:00")])))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    result = _bob(_run(db_path, config, publisher))

    assert result.status == SENT and len(publisher.calls) == 1  # the peers are not consulted unless the cap is switched on


def test_the_helper_returns_nothing_when_the_cap_is_not_set(db_path, monkeypatch):
    monkeypatch.delenv(CAP_ENV, raising=False)

    assert shared_cap_from_environment(db_path) is None


@pytest.mark.parametrize("bad", ["two", "-1", "1.5"])
def test_a_bad_cap_value_is_an_error_not_a_default(db_path, monkeypatch, bad):
    monkeypatch.setenv(CAP_ENV, bad)

    with pytest.raises(ValueError):
        shared_cap_from_environment(db_path)


# --- the point of it ----------------------------------------------------------------------------------------------------------------------


def test_a_person_another_agent_already_nudged_today_is_not_nudged_by_p1(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, str(_peer(tmp_path, [("bob", DAY.isoformat(), "2026-06-01T08:00:00+00:00")])))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)  # P1 would otherwise send unattended

    result = _bob(_run(db_path, config, publisher))

    assert result.status == CAP_REACHED and "1 from another agent" in result.detail
    assert publisher.calls == [] and _proposals(db_path) == 0  # not sent, and not even planned


def test_a_nudge_the_other_agent_sent_yesterday_does_not_count_today(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, str(_peer(tmp_path, [("bob", "2026-05-31", "2026-05-31T08:00:00+00:00")])))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    assert _bob(_run(db_path, config, publisher)).status == SENT


def test_a_nudge_the_other_agent_planned_but_never_delivered_does_not_count(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, str(_peer(tmp_path, [("bob", DAY.isoformat(), None)])))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    assert _bob(_run(db_path, config, publisher)).status == SENT


def test_someone_else_is_not_caught_up_in_bobs_cap(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, str(_peer(tmp_path, [("alice", DAY.isoformat(), "2026-06-01T08:00:00+00:00")])))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    assert _bob(_run(db_path, config, publisher)).status == SENT


def test_the_cap_value_is_configuration(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv(PEERS_ENV, str(_peer(tmp_path, [("bob", DAY.isoformat(), "2026-06-01T08:00:00+00:00")])))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)
    monkeypatch.setenv(CAP_ENV, "1")
    assert _bob(_run(db_path, config, publisher)).status == CAP_REACHED

    monkeypatch.setenv(CAP_ENV, "2")  # the same situation under a cap of two

    assert _bob(_run(db_path, config, publisher)).status == SENT


def test_a_nudge_in_another_p1_channel_counts_too(db_path, monkeypatch):
    """P1's own cap is per channel; the shared one is per person: a nudge to bob in a different channel counts against him."""
    NudgeStore(db_path).record(channel_id="other-channel", member_id="bob", date=DAY.isoformat(), idempotency_key="o1", proposal_id="p")
    NudgeStore(db_path).mark_sent(idempotency_key="o1", sent_at="2026-06-01T08:00:00+00:00")
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    monkeypatch.setenv(CAP_ENV, "1")  # no peers listed: only P1's own ledger, but across every channel
    refused = _bob(_run(db_path, config, publisher))
    assert refused.status == CAP_REACHED and "1 from P1, 0 from another agent" in refused.detail and publisher.calls == []

    monkeypatch.delenv(CAP_ENV)  # off: only the per-channel cap applies, and nudge-channel's has not been reached
    assert _bob(_run(db_path, config, publisher)).status == SENT


def test_the_two_agents_nudges_add_up(db_path, tmp_path):
    peer = _peer(tmp_path, [("bob", DAY.isoformat(), "2026-06-01T08:00:00+00:00")])
    NudgeStore(db_path).record(channel_id="other-channel", member_id="bob", date=DAY.isoformat(), idempotency_key="o1", proposal_id="p")
    NudgeStore(db_path).mark_sent(idempotency_key="o1", sent_at="2026-06-01T09:00:00+00:00")

    reading = SharedNudgeCap(db_path=db_path, cap=2, peer_paths=[peer]).reading("bob", DAY.isoformat())

    assert (reading.own, reading.peers, reading.total) == (1, 1, 2) and reading.reached


# --- the same person under different ids ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name_table", ["assignees", "members"])
def test_a_person_the_other_agent_knows_by_a_different_id_still_counts(db_path, tmp_path, monkeypatch, name_table):
    """P1 knows 'bob' (Bob Brown); the other agent nudged 'bob.brown' whose name is 'Bob Brown'."""
    peer = _peer(tmp_path, [("bob.brown", DAY.isoformat(), "2026-06-01T08:00:00+00:00")], [("bob.brown", " BOB brown ")], name_table)

    assert SharedNudgeCap(db_path=db_path, cap=1, peer_paths=[peer]).reading("bob", DAY.isoformat()).peers == 1


def test_a_person_with_a_name_nobody_else_has_is_not_counted(db_path, tmp_path):
    peer = _peer(tmp_path, [("someone", DAY.isoformat(), "2026-06-01T08:00:00+00:00")], [("someone", "Someone Else")])

    assert SharedNudgeCap(db_path=db_path, cap=1, peer_paths=[peer]).reading("bob", DAY.isoformat()).peers == 0


def test_two_people_with_one_name_in_the_other_agent_are_both_counted(db_path, tmp_path):
    peer = _peer(tmp_path, [("b1", DAY.isoformat(), "x"), ("b2", DAY.isoformat(), "y")], [("b1", "Bob Brown"), ("b2", "Bob Brown")])

    assert SharedNudgeCap(db_path=db_path, cap=1, peer_paths=[peer]).reading("bob", DAY.isoformat()).peers == 2  # not knowing which, count both


# --- it fails closed, and only reads ---------------------------------------------------------------------------------------------------


def test_an_unreadable_peer_ledger_means_nobody_is_nudged(db_path, tmp_path, monkeypatch):
    broken = tmp_path / "broken.db"
    broken.write_text("not a database")
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, str(broken))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    result = _bob(_run(db_path, config, publisher))

    assert result.status == CAP_UNAVAILABLE and publisher.calls == [] and _proposals(db_path) == 0


def test_a_peer_ledger_that_is_listed_but_missing_means_nobody_is_nudged(db_path, tmp_path, monkeypatch):
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, str(tmp_path / "gone.db"))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    assert _bob(_run(db_path, config, publisher)).status == CAP_UNAVAILABLE and publisher.calls == []


def test_a_peer_database_without_a_nudges_table_is_unreadable_not_empty(db_path, tmp_path):
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()

    with pytest.raises(SharedCapUnavailableError):
        SharedNudgeCap(db_path=db_path, cap=1, peer_paths=[empty]).reading("bob", DAY.isoformat())


def test_the_peer_ledger_is_never_written_to(db_path, tmp_path, monkeypatch):
    peer = _peer(tmp_path, [("alice", DAY.isoformat(), "2026-06-01T08:00:00+00:00")], [("alice", "Alice Anders")])
    before = peer.read_bytes()
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, str(peer))
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    _run(db_path, config, publisher)

    assert peer.read_bytes() == before


def test_several_peer_ledgers_are_all_consulted(db_path, tmp_path, monkeypatch):
    one = _peer(tmp_path, [])
    two_dir = tmp_path / "two"
    two_dir.mkdir()
    two = _peer(two_dir, [("bob", DAY.isoformat(), "2026-06-01T08:00:00+00:00")])
    monkeypatch.setenv(CAP_ENV, "1")
    monkeypatch.setenv(PEERS_ENV, f"{one}, {two}")
    config, publisher = _config(), _Recorder()
    _make_bob_previously_nudged(db_path, config, publisher)

    assert _bob(_run(db_path, config, publisher)).status == CAP_REACHED


# --- checked again when a waiting nudge is finally sent -------------------------------------------------------------------------------


def test_a_first_nudge_approved_after_another_agent_chased_the_person_is_not_sent(db_path, tmp_path, monkeypatch):
    """bob's first nudge ever waits for approval. The other agent nudges him. The approval then arrives: the next run must not send."""
    monkeypatch.setenv(CAP_ENV, "1")
    peer_path = _peer(tmp_path, [])
    monkeypatch.setenv(PEERS_ENV, str(peer_path))
    config, publisher = _config(), _Recorder()
    first = _bob(_run(db_path, config, publisher))
    assert first.status == "awaiting_approval" and publisher.calls == []

    conn = sqlite3.connect(peer_path)
    conn.execute("INSERT INTO nudges (member_id, date, sent_at, idempotency_key) VALUES ('bob', ?, '2026-06-01T10:00:00+00:00', 'late')", (DAY.isoformat(),))
    conn.commit()
    conn.close()
    store = ProposalStore(db_path)
    store.approve(store.get_by_idempotency_key(f"nudge-channel:bob:{DAY.isoformat()}:1").id, approver_id="priya")

    after = _bob(_run(db_path, config, publisher))

    assert after.status == CAP_REACHED and publisher.calls == []
