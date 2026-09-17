"""
SPN-09's own acceptance test: "An automated test calling each outbound
path directly for a pending and a rejected proposal fails every time."
Also covers the "documented timeout behaviour defaulting to not
sending" requirement concretely, and that a successful send is
recorded and marks the proposal applied.
"""

from __future__ import annotations

import json

import pytest

from p1.approval.proposals import APPLIED, APPROVED, PENDING, REJECTED, ProposalStore
from p1.approval.write_guard import WriteRefusedError, guarded_send
from p1.storage.db import get_connection, init_db


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


@pytest.fixture
def store(db_path):
    return ProposalStore(db_path)


class _Recorder:
    """A stand-in send_fn -- records whether it was ever actually
    called, which is the thing that must never happen for a refused
    send, not merely that an exception was raised."""

    def __init__(self, return_value="sent!"):
        self.called = False
        self.return_value = return_value

    def __call__(self):
        self.called = True
        return self.return_value


class _RaisingSendFn:
    def __init__(self):
        self.called = False

    def __call__(self):
        self.called = True
        raise RuntimeError("the publish adapter is down")


class _UnreachableStore:
    """Simulates a lookup that fails for reasons that have nothing to
    do with the proposal's own status -- a database error, or, in a
    future networked ProposalStore, a genuine timeout."""

    def get(self, proposal_id):
        raise TimeoutError("proposal store unreachable")


def _make_proposal(store, status, *, suffix):
    proposal = store.create(
        type="daily_digest",
        payload={"content": f"digest content {suffix}"},
        original_model_output={"content": f"digest content {suffix}"},
        source_refs=["m1"],
        idempotency_key=f"key-{suffix}",
    )
    if status in (APPROVED, APPLIED):
        proposal = store.approve(proposal.id, approver_id="priya")
    if status == REJECTED:
        proposal = store.reject(proposal.id, approver_id="priya")
    if status == APPLIED:
        proposal = store.apply(proposal.id)
    return proposal


# --- SPN-09's own acceptance test: every outbound path, pending and rejected --


@pytest.mark.parametrize("status", [PENDING, REJECTED])
@pytest.mark.parametrize(
    "action_type,target",
    [
        ("channel_post", "channel-1"),
        ("nudge", "member-bob"),
        ("escalation", "member-owner"),
    ],
)
def test_each_outbound_path_refuses_a_pending_or_rejected_proposal_every_time(
    store, db_path, status, action_type, target,
):
    proposal = _make_proposal(store, status, suffix=f"{status}-{action_type}")
    send_fn = _Recorder()

    with pytest.raises(WriteRefusedError):
        guarded_send(
            proposal.id, action_type=action_type, target=target, send_fn=send_fn, db_path=db_path,
        )

    assert send_fn.called is False


def test_an_already_applied_proposal_also_refuses_a_second_send(store, db_path):
    """Applied is not approved -- guarded_send() is not just a
    pending/rejected check, it requires the current status to be
    exactly 'approved', so a proposal already sent once cannot be sent
    again through this path either."""
    proposal = _make_proposal(store, APPLIED, suffix="already-applied")
    send_fn = _Recorder()

    with pytest.raises(WriteRefusedError):
        guarded_send(proposal.id, action_type="channel_post", target="c1", send_fn=send_fn, db_path=db_path)

    assert send_fn.called is False


def test_an_unknown_proposal_id_refuses_and_never_calls_send_fn(db_path):
    send_fn = _Recorder()
    with pytest.raises(WriteRefusedError):
        guarded_send(
            "does-not-exist", action_type="channel_post", target="c1", send_fn=send_fn, db_path=db_path,
        )
    assert send_fn.called is False


def test_a_lookup_timeout_refuses_rather_than_sending(db_path):
    """The documented timeout behaviour, made concrete: a store whose
    lookup raises TimeoutError is treated exactly like any other
    failure to confirm approval -- refuse, never send."""
    send_fn = _Recorder()
    with pytest.raises(WriteRefusedError):
        guarded_send(
            "some-id", action_type="channel_post", target="c1", send_fn=send_fn,
            store=_UnreachableStore(), db_path=db_path,
        )
    assert send_fn.called is False


# --- the approved path: sent, marked applied, logged ----------------------


def test_an_approved_proposal_is_sent_and_marked_applied(store, db_path):
    proposal = _make_proposal(store, APPROVED, suffix="approved")
    send_fn = _Recorder(return_value="ok")

    result = guarded_send(proposal.id, action_type="channel_post", target="c1", send_fn=send_fn, db_path=db_path)

    assert send_fn.called is True
    assert result == "ok"
    assert store.get(proposal.id).status == APPLIED


def test_a_send_fn_exception_propagates_and_the_proposal_is_not_applied(store, db_path):
    proposal = _make_proposal(store, APPROVED, suffix="send-fails")
    send_fn = _RaisingSendFn()

    with pytest.raises(RuntimeError, match="publish adapter is down"):
        guarded_send(proposal.id, action_type="channel_post", target="c1", send_fn=send_fn, db_path=db_path)

    assert send_fn.called is True
    # The refusal machinery never ran (this wasn't a WriteRefusedError),
    # but the send genuinely failed, so it must not have been marked
    # applied either -- a failed send is not a sent one.
    assert store.get(proposal.id).status == APPROVED


# --- write_log: every attempt is a row you can show on camera -------------


def _write_log_rows(db_path):
    conn = get_connection(db_path)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM write_log ORDER BY id").fetchall()]
    finally:
        conn.close()


def test_a_refused_send_for_an_unknown_id_logs_with_no_proposal_id(db_path):
    send_fn = _Recorder()
    with pytest.raises(WriteRefusedError):
        guarded_send("ghost-id", action_type="nudge", target="member-1", send_fn=send_fn, db_path=db_path)

    rows = _write_log_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["proposal_id"] is None
    assert rows[0]["status"] == "refused"
    assert rows[0]["action_type"] == "nudge"
    assert rows[0]["target"] == "member-1"
    assert json.loads(rows[0]["payload"])["attempted_proposal_id"] == "ghost-id"


def test_a_refused_send_for_a_pending_proposal_logs_its_real_proposal_id(store, db_path):
    proposal = _make_proposal(store, PENDING, suffix="log-pending")
    send_fn = _Recorder()
    with pytest.raises(WriteRefusedError):
        guarded_send(proposal.id, action_type="escalation", target="owner-1", send_fn=send_fn, db_path=db_path)

    rows = _write_log_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["proposal_id"] == proposal.id
    assert rows[0]["status"] == "refused"
    assert json.loads(rows[0]["payload"])["proposal_status"] == PENDING


def test_a_successful_send_logs_a_sent_row_with_the_payload(store, db_path):
    proposal = _make_proposal(store, APPROVED, suffix="log-sent")
    send_fn = _Recorder()
    guarded_send(proposal.id, action_type="channel_post", target="c1", send_fn=send_fn, db_path=db_path)

    rows = _write_log_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["proposal_id"] == proposal.id
    assert rows[0]["status"] == "sent"
    assert json.loads(rows[0]["payload"])["payload"] == proposal.payload


def test_a_failed_send_logs_a_send_failed_row(store, db_path):
    proposal = _make_proposal(store, APPROVED, suffix="log-failed")
    send_fn = _RaisingSendFn()
    with pytest.raises(RuntimeError):
        guarded_send(proposal.id, action_type="channel_post", target="c1", send_fn=send_fn, db_path=db_path)

    rows = _write_log_rows(db_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "send_failed"
