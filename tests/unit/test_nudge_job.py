"""
CHN-21's own acceptance test, in two parts:

  - "The on-leave member is never nudged under any path" --
    test_on_leave_member_is_never_nudged_via_the_real_ledger and
    test_on_leave_member_is_never_nudged_even_if_the_ledger_mislabels_them
    cover, respectively, the ordinary path (build_ledger() itself
    already marks them EXCLUDED) and the defensive path
    (run_nudge_job's own independent per-member exceptions check,
    proven by handing the job a deliberately mislabelled record).

  - "The cap holds across repeated runs in one day" --
    test_cap_holds_across_repeated_runs_in_one_day and
    test_a_higher_cap_allows_more_than_one_nudge_the_same_day, the same
    "run it three times, count what actually got sent" posture CHN-18's
    GC6 already established for the daily digest.

The rest of this file walks run_nudge_job's status-machine branching
the same way test_daily_job.py walks run_daily_digest_job's: off by
default, skip on a non-working day, first-nudge-to-a-person requires
approval and a rerun before approval never re-proposes or sends, a
rejected nudge never sends on any rerun, and a previously-nudged
person's next nudge auto-approves and runs unattended.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.approval.proposals import APPLIED, PENDING, ProposalStore
from p1.config.schema import ChannelConfig
from p1.nudges.nudge_job import (
    ALREADY_SENT,
    AUTO_APPROVE_APPROVER_ID,
    AWAITING_APPROVAL,
    CAP_REACHED,
    DISABLED,
    EXCLUDED_STATUS,
    REJECTED_STATUS,
    SENT,
    SKIPPED_NON_WORKING_DAY,
    run_nudge_job,
)
from p1.participation.ledger import NO_MESSAGE, POSTED_NO_UPDATE, ParticipationRecord
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.nudges_repo import NudgeStore

DAY1 = date(2026, 6, 1)  # Monday
DAY2 = date(2026, 6, 8)  # the following Monday
SATURDAY = date(2026, 6, 6)


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "nudge-channel",
        "display_name": "Nudge Test Channel",
        "roster": ["alice", "bob", "carol"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": "UTC",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "non_working_dates": [],
        "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
        "exceptions": [{"member_id": "carol", "reason": "On leave"}],
        "nudge_enabled": True,
        "nudge_cap_per_day": 1,
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    try:
        conn.execute(
            "INSERT INTO channels (id, display_name, allowlisted) VALUES ('nudge-channel', 'C', 1)"
        )
        for member_id in ("alice", "bob", "carol"):
            conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()
    return path


def _seed_message(db_path, message_id, author_id, day, label):
    MessageStore(db_path).upsert_messages(
        [
            TeamsMessage(
                id=message_id, channel_id="nudge-channel", author_id=author_id,
                posted_at=f"{day.isoformat()}T09:30:00+00:00", body="text",
            )
        ]
    )
    ClassificationStore(db_path).record(message_id=message_id, label=label, method="model", confidence=0.9)


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def send_direct_message(self, member_id: str, content: str) -> dict:
        self.calls.append((member_id, content))
        return {"ok": True}


def _result_for(results, member_id):
    matches = [r for r in results if r.member_id == member_id]
    assert len(matches) == 1, f"expected exactly one result for {member_id!r}, got {matches}"
    return matches[0]


def _nudge_proposal_count(db_path, channel_id, member_id, day):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE idempotency_key LIKE ?",
            (f"{channel_id}:{member_id}:{day.isoformat()}:%",),
        ).fetchone()["n"]
    finally:
        conn.close()


def _write_log_rows_for(db_path, member_id):
    conn = get_connection(db_path)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM write_log WHERE action_type = 'nudge' AND target = ? ORDER BY id", (member_id,)
            ).fetchall()
        ]
    finally:
        conn.close()


# --- off by default / non-working day ---------------------------------------


def test_disabled_channel_produces_no_proposals(db_path):
    config = _config(nudge_enabled=False)
    _seed_message(db_path, "m1", "bob", DAY1, "chatter")  # bob would otherwise be a non-responder
    publisher = _RecordingPublisher()

    results = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)

    assert len(results) == 1
    assert results[0].status == DISABLED
    assert publisher.calls == []
    assert _nudge_proposal_count(db_path, config.channel_id, "bob", DAY1) == 0


def test_skips_a_non_working_day_without_generating_anything(db_path):
    config = _config()
    publisher = _RecordingPublisher()

    results = run_nudge_job(config.channel_id, config, publisher, day=SATURDAY, db_path=db_path)

    assert len(results) == 1
    assert results[0].status == SKIPPED_NON_WORKING_DAY
    assert publisher.calls == []


# --- CHN-21's own acceptance test, part 1: never the excluded ---------------


def test_on_leave_member_is_never_nudged_via_the_real_ledger(db_path):
    config = _config()  # carol is on the exceptions list
    # alice contributes; bob and carol both post nothing today.
    _seed_message(db_path, "m1", "alice", DAY1, "update")
    publisher = _RecordingPublisher()

    results = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)

    member_ids = {r.member_id for r in results}
    assert "carol" not in member_ids  # never a candidate at all -- build_ledger() marks her EXCLUDED
    assert "bob" in member_ids
    assert NudgeStore(db_path).has_ever_been_nudged(config.channel_id, "carol") is False
    assert all(call[0] != "carol" for call in publisher.calls)


def test_on_leave_member_is_never_nudged_even_if_the_ledger_mislabels_them(db_path):
    """A defensive test: if build_ledger() itself were ever wrong and
    handed this job a NO_MESSAGE record for an excepted member, the
    job's own independent exceptions check must still refuse to nudge
    them -- this is what "never... under any path" actually means."""
    config = _config()
    mislabelled_records = [
        ParticipationRecord(
            channel_id=config.channel_id, member_id="carol", date=DAY1.isoformat(),
            state=NO_MESSAGE, evidence_message_ids=(),
        ),
    ]
    publisher = _RecordingPublisher()

    results = run_nudge_job(
        config.channel_id, config, publisher, day=DAY1, db_path=db_path, ledger_records=mislabelled_records,
    )

    assert len(results) == 1
    assert results[0].member_id == "carol"
    assert results[0].status == EXCLUDED_STATUS
    assert publisher.calls == []
    assert _nudge_proposal_count(db_path, config.channel_id, "carol", DAY1) == 0
    assert NudgeStore(db_path).has_ever_been_nudged(config.channel_id, "carol") is False


# --- first nudge to a person requires approval ------------------------------


def test_first_nudge_ever_to_a_person_creates_a_pending_proposal_and_does_not_send(db_path):
    config = _config()
    publisher = _RecordingPublisher()

    results = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)

    bob_result = _result_for(results, "bob")
    assert bob_result.status == AWAITING_APPROVAL
    assert publisher.calls == []
    proposal = ProposalStore(db_path).get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1")
    assert proposal is not None
    assert proposal.status == PENDING


def test_reruns_before_approval_never_duplicate_the_proposal_or_send(db_path):
    config = _config()
    publisher = _RecordingPublisher()

    for _ in range(3):
        results = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
        assert _result_for(results, "bob").status == AWAITING_APPROVAL

    assert publisher.calls == []
    assert _nudge_proposal_count(db_path, config.channel_id, "bob", DAY1) == 1
    refused_rows = [row for row in _write_log_rows_for(db_path, "bob") if row["status"] == "refused"]
    assert len(refused_rows) == 3


def test_after_human_approval_a_rerun_sends_and_marks_applied(db_path):
    config = _config()
    publisher = _RecordingPublisher()

    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1")
    proposal_store.approve(proposal.id, approver_id="priya")

    results = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)

    bob_result = _result_for(results, "bob")
    assert bob_result.status == SENT
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] == "bob"
    assert proposal_store.get(proposal.id).status == APPLIED
    assert NudgeStore(db_path).has_ever_been_nudged(config.channel_id, "bob") is True


def test_a_rejected_nudge_never_sends_on_any_rerun(db_path):
    config = _config()
    publisher = _RecordingPublisher()

    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1")
    proposal_store.reject(proposal.id, approver_id="priya")

    first = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    second = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)

    assert _result_for(first, "bob").status == REJECTED_STATUS
    assert _result_for(second, "bob").status == REJECTED_STATUS
    assert publisher.calls == []


# --- a previously-nudged person is auto-approved and sent unattended -------


def test_a_previously_nudged_person_is_auto_approved_and_sent_unattended(db_path):
    config = _config()
    publisher = _RecordingPublisher()

    # Day 1: bob's first-ever nudge in this channel -- awaits a human,
    # as proven above.
    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    day1_proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1")
    proposal_store.approve(day1_proposal.id, approver_id="priya")
    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    assert NudgeStore(db_path).has_ever_been_nudged(config.channel_id, "bob") is True

    # Day 2 (a different day -- bob is a non-responder again): nobody
    # approves anything -- the job itself must auto-approve and send in
    # the same run.
    results = run_nudge_job(config.channel_id, config, publisher, day=DAY2, db_path=db_path)

    bob_result = _result_for(results, "bob")
    assert bob_result.status == SENT
    assert len(publisher.calls) == 2
    day2_proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY2.isoformat()}:1")
    assert day2_proposal.approver_id == AUTO_APPROVE_APPROVER_ID
    assert day2_proposal.status == APPLIED


# --- CHN-21's own acceptance test, part 2: the cap holds --------------------


def test_cap_holds_across_repeated_runs_in_one_day(db_path):
    config = _config(nudge_cap_per_day=1)
    publisher = _RecordingPublisher()

    # Make bob a previously-nudged person so today's nudge auto-approves
    # and actually sends -- the steady-state case the cap is meant to
    # bound, the same scenario-design choice CHN-18's GC6 made for the
    # daily digest's own idempotency check.
    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal_store.approve(
        proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1").id,
        approver_id="priya",
    )
    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    assert len(publisher.calls) == 1

    # Same day, three more reruns -- the cap of 1/day must hold no
    # matter how many times this job fires.
    statuses = []
    for _ in range(3):
        results = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
        statuses.append(_result_for(results, "bob").status)

    assert statuses == [CAP_REACHED, CAP_REACHED, CAP_REACHED]
    assert len(publisher.calls) == 1  # still just the one real send all day
    assert NudgeStore(db_path).sent_count_for_day(config.channel_id, "bob", DAY1.isoformat()) == 1
    assert _nudge_proposal_count(db_path, config.channel_id, "bob", DAY1) == 1


def test_a_higher_cap_allows_more_than_one_nudge_the_same_day(db_path):
    config = _config(nudge_cap_per_day=2)
    publisher = _RecordingPublisher()

    # bob is already a previously-nudged person (from an earlier day),
    # so every nudge today auto-approves.
    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal_store.approve(
        proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1").id,
        approver_id="priya",
    )
    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    assert len(publisher.calls) == 1

    # Day 2: cap is 2, bob has never been nudged on this day yet -- two
    # nudges today should both go out unattended (bob's history makes
    # every one of them auto-approve), and a third must be capped.
    second_run = run_nudge_job(config.channel_id, config, publisher, day=DAY2, db_path=db_path)
    assert _result_for(second_run, "bob").status == SENT
    third_run = run_nudge_job(config.channel_id, config, publisher, day=DAY2, db_path=db_path)
    assert _result_for(third_run, "bob").status == SENT
    fourth_run = run_nudge_job(config.channel_id, config, publisher, day=DAY2, db_path=db_path)
    assert _result_for(fourth_run, "bob").status == CAP_REACHED

    assert len(publisher.calls) == 1 + 2  # day 1's one send, plus day 2's two sends
    assert NudgeStore(db_path).sent_count_for_day(config.channel_id, "bob", DAY2.isoformat()) == 2


# --- reruns after a real send never resend ----------------------------------


def test_a_send_that_somehow_reruns_before_bookkeeping_reports_already_sent(db_path):
    """Exercises the ALREADY_SENT branch directly: if guarded_send()
    is ever called again for a proposal that is already APPLIED (e.g. a
    retried call racing the cap check), it must refuse -- never resend
    -- and this job must report that distinctly from a fresh cap being
    reached."""
    config = _config()
    publisher = _RecordingPublisher()

    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1")
    proposal_store.approve(proposal.id, approver_id="priya")
    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)
    assert proposal_store.get(proposal.id).status == APPLIED

    # Force the same already-applied proposal to be retried by wiping
    # this one nudge's own bookkeeping row's sent_at back to NULL, so
    # sent_count_for_day() under-reports and the cap check lets the job
    # attempt this member again this run.
    conn = get_connection(db_path)
    try:
        conn.execute(
            "UPDATE nudges SET sent_at = NULL WHERE idempotency_key = ?",
            (f"{config.channel_id}:bob:{DAY1.isoformat()}:1",),
        )
        conn.commit()
    finally:
        conn.close()

    results = run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)

    assert _result_for(results, "bob").status == ALREADY_SENT
    assert len(publisher.calls) == 1  # never resent


# --- message wording varies by ledger state, but is never model-generated --


def test_nudge_wording_differs_between_no_message_and_posted_no_update(db_path):
    conn = get_connection(db_path)
    try:
        conn.execute("INSERT INTO members (id, display_name) VALUES ('dave', 'dave')")
        conn.commit()
    finally:
        conn.close()
    config = _config(roster=["alice", "bob", "dave"], exceptions=[])
    _seed_message(db_path, "m1", "dave", DAY1, "chatter")  # posted, but nothing that counts
    publisher = _RecordingPublisher()

    run_nudge_job(config.channel_id, config, publisher, day=DAY1, db_path=db_path)

    proposal_store = ProposalStore(db_path)
    bob_proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:bob:{DAY1.isoformat()}:1")
    dave_proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:dave:{DAY1.isoformat()}:1")

    assert bob_proposal.payload["state"] == NO_MESSAGE
    assert dave_proposal.payload["state"] == POSTED_NO_UPDATE
    assert bob_proposal.payload["content"] != dave_proposal.payload["content"]
