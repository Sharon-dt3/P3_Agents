"""
CHN-25: p1.approval.service -- the one seam both surfaces call.

Covers all three proposal types the two real surfaces will ever need
to approve/reject (daily_digest_publish, nudge, escalation), each
dispatched by approve_and_send()'s own _resend_plan() -- proving that
dispatch reads back exactly the fields the job that created each
proposal actually wrote, never a second guess at their shape. The
cross-surface "identical audit records" claim itself is proven in
tests/unit/test_copilot_studio_connector.py, which calls this module
alongside the connector; this file is about the service's own
correctness in isolation.
"""

from __future__ import annotations

from datetime import date, time

from p1.adapters.teams_reader import TeamsMessage
from p1.approval import service
from p1.approval.proposals import APPLIED, REJECTED, ProposalStore
from p1.config.schema import ChannelConfig
from p1.escalations.escalation_job import run_escalation_job
from p1.nudges.nudge_job import run_nudge_job
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.escalations_repo import EscalationStore
from p1.storage.messages_repo import MessageStore
from p1.storage.nudges_repo import NudgeStore

CHANNEL_ID = "svc-channel"
FRI_PREV = date(2026, 5, 29)
MON = date(2026, 6, 1)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def post_direct_message(self, member_id: str, content: str) -> dict:
        self.calls.append(("dm", member_id, content))
        return {"ok": True}

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        self.calls.append(("channel", channel_id, content))
        return {"ok": True}


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID, "display_name": "Svc Channel",
        "roster": ["alice", "bob"],
        "update_window_start": time(9, 0), "update_window_end": time(11, 0),
        "timezone": "UTC", "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "daily_digest_time": time(9, 0), "weekly_digest_day": "Fri", "weekly_digest_time": time(16, 0),
        "channel_owner_id": "priya", "nudge_enabled": True, "nudge_cap_per_day": 1,
        "escalation_threshold_days": 1,
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def _seed_db(db_path) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'Svc Channel', 1)", (CHANNEL_ID,))
        for member_id in ("alice", "bob", "priya"):
            conn.execute("INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()


def _sync_config(db_path, config: ChannelConfig) -> None:
    """Populate channel_config directly -- escalation's resend needs a
    synced config to look the owner up from (see service._resend_plan)."""
    import json

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO channel_config (
                channel_id, roster, update_window_start, update_window_end, timezone,
                working_days, non_working_dates, length_floor, count_thread_replies, ignore_bots,
                daily_digest_time, weekly_digest_day, weekly_digest_time, nudge_enabled,
                nudge_cap_per_day, escalation_threshold_days, channel_owner_id, exceptions, version
            ) VALUES (:channel_id, :roster, :update_window_start, :update_window_end, :timezone,
                :working_days, :non_working_dates, :length_floor, :count_thread_replies, :ignore_bots,
                :daily_digest_time, :weekly_digest_day, :weekly_digest_time, :nudge_enabled,
                :nudge_cap_per_day, :escalation_threshold_days, :channel_owner_id, :exceptions, :version)
            """,
            {
                "channel_id": config.channel_id,
                "roster": json.dumps(config.roster),
                "update_window_start": config.update_window_start.isoformat(),
                "update_window_end": config.update_window_end.isoformat(),
                "timezone": config.timezone,
                "working_days": json.dumps(config.working_days),
                "non_working_dates": json.dumps([d.isoformat() for d in config.non_working_dates]),
                "length_floor": config.length_floor,
                "count_thread_replies": int(config.count_thread_replies),
                "ignore_bots": int(config.ignore_bots),
                "daily_digest_time": config.daily_digest_time.isoformat(),
                "weekly_digest_day": config.weekly_digest_day,
                "weekly_digest_time": config.weekly_digest_time.isoformat(),
                "nudge_enabled": int(config.nudge_enabled),
                "nudge_cap_per_day": config.nudge_cap_per_day,
                "escalation_threshold_days": config.escalation_threshold_days,
                "channel_owner_id": config.channel_owner_id,
                "exceptions": json.dumps([e.model_dump() for e in config.exceptions]),
                "version": config.version,
            },
        )
        conn.commit()
    finally:
        conn.close()


def _seed_message(db_path, message_id, author_id, day) -> None:
    MessageStore(db_path).upsert_messages(
        [TeamsMessage(id=message_id, channel_id=CHANNEL_ID, author_id=author_id,
                      posted_at=f"{day.isoformat()}T09:30:00+00:00", body="text")]
    )
    ClassificationStore(db_path).record(message_id=message_id, label="update", method="model", confidence=0.9)


def test_list_pending_approvals_shows_a_freshly_created_nudge(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    config = _config()
    _seed_message(db_path, "alice-mon", "alice", MON)  # bob never posts -> non-responder

    run_nudge_job(CHANNEL_ID, config, _RecordingPublisher(), day=MON, db_path=db_path)

    pending = service.list_pending_approvals(db_path=db_path)
    assert len(pending) == 1
    assert pending[0].type == "nudge"
    assert pending[0].channel_id == CHANNEL_ID
    assert "bob" in pending[0].summary


def test_approve_and_send_a_nudge_sends_and_records_audit(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    config = _config()
    _seed_message(db_path, "alice-mon", "alice", MON)
    publisher = _RecordingPublisher()

    run_nudge_job(CHANNEL_ID, config, publisher, day=MON, db_path=db_path)
    proposal_id = service.list_pending_approvals(db_path=db_path)[0].proposal_id

    result = service.approve_and_send(proposal_id, approver_id="priya", publisher=publisher, db_path=db_path)

    assert result.outcome == "sent"
    assert ("dm", "bob") in [(c[0], c[1]) for c in publisher.calls]
    assert ProposalStore(db_path).get(proposal_id).status == APPLIED

    conn = get_connection(db_path)
    try:
        write_log_row = conn.execute(
            "SELECT * FROM write_log WHERE proposal_id = ? AND status = 'sent'", (proposal_id,)
        ).fetchone()
        audit_row = conn.execute(
            "SELECT * FROM audit WHERE entity_id = ? AND action = 'proposal.approved'", (proposal_id,)
        ).fetchone()
    finally:
        conn.close()
    assert write_log_row is not None
    assert write_log_row["action_type"] == "nudge"
    assert write_log_row["target"] == "bob"
    assert audit_row is not None
    assert audit_row["actor"] == "priya"


def test_approve_and_send_an_escalation_looks_up_the_current_owner(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    config = _config(escalation_threshold_days=1)
    _sync_config(db_path, config)
    publisher = _RecordingPublisher()
    nudge_store = NudgeStore(db_path)
    escalation_store = EscalationStore(db_path)

    # bob has an anchor contribution the day before, then misses MON --
    # 1-day threshold, already nudged, so this creates a pending
    # escalation on the first call.
    _seed_message(db_path, "bob-anchor", "bob", FRI_PREV)
    _seed_message(db_path, "alice-mon", "alice", MON)
    nudge_store.record(channel_id=CHANNEL_ID, member_id="bob", date=FRI_PREV.isoformat(),
                        idempotency_key="pre-existing-nudge", proposal_id="n/a")
    nudge_store.mark_sent(idempotency_key="pre-existing-nudge", sent_at="2026-05-29T09:00:00+00:00")

    run_escalation_job(CHANNEL_ID, config, publisher, day=MON, db_path=db_path,
                        escalation_store=escalation_store, nudge_store=nudge_store)

    pending = service.list_pending_approvals(db_path=db_path)
    assert len(pending) == 1
    assert pending[0].type == "escalation"
    proposal_id = pending[0].proposal_id

    # Channel owner changes AFTER the escalation was created, before approval.
    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE channel_config SET channel_owner_id = ? WHERE channel_id = ?", ("new_owner", CHANNEL_ID))
        conn.execute("INSERT INTO members (id, display_name) VALUES ('new_owner', 'new_owner')")
        conn.commit()
    finally:
        conn.close()

    result = service.approve_and_send(proposal_id, approver_id="priya", publisher=publisher, db_path=db_path)

    assert result.outcome == "sent"
    assert ("dm", "new_owner") in [(c[0], c[1]) for c in publisher.calls]


def test_approve_and_send_a_channel_post(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    publisher = _RecordingPublisher()
    store = ProposalStore(db_path)
    proposal = store.create(
        type="daily_digest_publish",
        payload={"channel_id": CHANNEL_ID, "date": MON.isoformat(), "target_channel": CHANNEL_ID, "content": "Daily digest"},
        original_model_output={}, source_refs=[], idempotency_key=f"{CHANNEL_ID}:{MON.isoformat()}:daily_publish",
    )

    result = service.approve_and_send(proposal.id, approver_id="priya", publisher=publisher, db_path=db_path)

    assert result.outcome == "sent"
    assert ("channel", CHANNEL_ID, "Daily digest") in publisher.calls


def test_reject_records_audit_and_a_later_approve_is_refused(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    store = ProposalStore(db_path)
    proposal = store.create(
        type="nudge", payload={"channel_id": CHANNEL_ID, "member_id": "bob", "date": MON.isoformat(), "content": "hi"},
        original_model_output={}, source_refs=[], idempotency_key="reject-me",
    )

    result = service.reject(proposal.id, approver_id="priya", db_path=db_path)
    assert result.outcome == "rejected"
    assert store.get(proposal.id).status == REJECTED

    conn = get_connection(db_path)
    try:
        audit_row = conn.execute(
            "SELECT * FROM audit WHERE entity_id = ? AND action = 'proposal.rejected'", (proposal.id,)
        ).fetchone()
    finally:
        conn.close()
    assert audit_row is not None

    # Already rejected -- a later approve is refused, never silently allowed.
    second = service.approve_and_send(proposal.id, approver_id="priya", publisher=_RecordingPublisher(), db_path=db_path)
    assert second.outcome == "refused"
    assert store.get(proposal.id).status == REJECTED


def test_list_pending_approvals_excludes_decided_proposals(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    store = ProposalStore(db_path)
    p1 = store.create(type="nudge", payload={"channel_id": CHANNEL_ID, "member_id": "a", "date": "2026-06-01", "content": "x"},
                       original_model_output={}, source_refs=[], idempotency_key="k1")
    p2 = store.create(type="nudge", payload={"channel_id": CHANNEL_ID, "member_id": "b", "date": "2026-06-01", "content": "y"},
                       original_model_output={}, source_refs=[], idempotency_key="k2")
    store.reject(p2.id, approver_id="priya")

    pending_ids = {p.proposal_id for p in service.list_pending_approvals(db_path=db_path)}
    assert pending_ids == {p1.id}
