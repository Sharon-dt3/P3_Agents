"""
CHN-23's own acceptance test: "With the threshold at three days, exactly
the seeded members missing three consecutive days are escalated, each
with a dated evidence bundle."

Four guarantees, each with its own tests, mirroring test_nudge_job.py's
own structure:

  - Threshold-driven: below-threshold produces no escalation at all
    (test_below_threshold_produces_no_escalation_and_no_proposal).

  - Never the excluded, checked twice, independently
    (test_excluded_member_is_never_escalated_via_the_real_ledger,
    test_excluded_member_is_never_escalated_even_if_the_ledger_mislabels_them).

  - Nudge precedes escalation, enforced as a real gate
    (test_a_member_who_has_never_been_nudged_is_not_escalated_even_past_threshold).

  - Per-streak cap, per-person approval gating
    (test_first_escalation_ever_..., test_reruns_before_approval_...,
    test_after_human_approval_..., test_a_rejected_escalation_...,
    test_the_same_continuous_streak_is_never_escalated_twice,
    test_a_broken_streak_that_recurs_creates_a_new_escalation_and_auto_approves).
"""

from __future__ import annotations

from datetime import date, time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.approval.proposals import APPLIED, PENDING, ProposalStore
from p1.config.schema import ChannelConfig
from p1.escalations.escalation_job import (
    ALREADY_SENT,
    AUTO_APPROVE_APPROVER_ID,
    AWAITING_APPROVAL,
    AWAITING_NUDGE,
    BELOW_THRESHOLD,
    EXCLUDED_STATUS,
    REJECTED_STATUS,
    SENT,
    SKIPPED_NON_WORKING_DAY,
    run_escalation_job,
)
from p1.participation.ledger import NO_MESSAGE, POSTED_NO_UPDATE, ParticipationRecord
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.escalations_repo import EscalationStore
from p1.storage.messages_repo import MessageStore
from p1.storage.nudges_repo import NudgeStore

FRI_PREV = date(2026, 5, 29)  # the working day immediately before MON
MON = date(2026, 6, 1)
TUE = date(2026, 6, 2)
WED = date(2026, 6, 3)
THU = date(2026, 6, 4)
FRI = date(2026, 6, 5)
SATURDAY = date(2026, 6, 6)
MON2 = date(2026, 6, 8)
TUE2 = date(2026, 6, 9)
WED2 = date(2026, 6, 10)


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "esc-channel",
        "display_name": "Escalation Test Channel",
        "roster": ["alice", "bob", "dave", "carol"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": "UTC",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "non_working_dates": [],
        "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "priya",
        "exceptions": [{"member_id": "carol", "reason": "On leave"}],
        "nudge_enabled": True,
        "nudge_cap_per_day": 1,
        "escalation_threshold_days": 3,
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
            "INSERT INTO channels (id, display_name, allowlisted) VALUES ('esc-channel', 'C', 1)"
        )
        for member_id in ("alice", "bob", "dave", "carol", "priya"):
            conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()
    return path


def _seed_message(db_path, message_id, author_id, day, label):
    MessageStore(db_path).upsert_messages(
        [
            TeamsMessage(
                id=message_id, channel_id="esc-channel", author_id=author_id,
                posted_at=f"{day.isoformat()}T09:30:00+00:00", body="text",
            )
        ]
    )
    ClassificationStore(db_path).record(message_id=message_id, label=label, method="model", confidence=0.9)


def _seed_contributes(db_path, member_id, day, msg_id_prefix):
    _seed_message(db_path, f"{msg_id_prefix}-{day.isoformat()}", member_id, day, "update")


def _seed_anchor(db_path, member_id):
    """Seeds a real contribution on FRI_PREV, the working day just
    before this file's MON..FRI test window. _streak_dates_ending_at()
    walks backward for real, exactly like production would against a
    channel with genuine history -- without this anchor, an empty
    fixture's "no messages at all before MON" would itself look like an
    unbroken run of missed days stretching indefinitely into the past,
    which is a fixture-completeness problem, not a job bug: any real
    channel has *some* prior history, even if it's just one earlier
    contribution establishing "this is where the silence started."""
    _seed_contributes(db_path, member_id, FRI_PREV, "anchor")


def _seed_previously_nudged(db_path, channel_id, member_id):
    """Bypasses run_nudge_job entirely -- this test file's job is
    escalation, not nudging, so a person's nudge history is seeded
    directly via NudgeStore, the same shortcut test_nudge_job.py takes
    with proposal approval rather than re-deriving it through the full
    nudge flow."""
    NudgeStore(db_path).record(
        channel_id=channel_id, member_id=member_id, date=MON.isoformat(),
        idempotency_key=f"{channel_id}:{member_id}:seed-nudge", proposal_id="seed-proposal",
    )
    NudgeStore(db_path).mark_sent(
        idempotency_key=f"{channel_id}:{member_id}:seed-nudge", sent_at="2026-05-25T09:00:00+00:00",
    )


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def post_direct_message(self, member_id: str, content: str) -> dict:
        self.calls.append((member_id, content))
        return {"ok": True}


def _result_for(results, member_id):
    matches = [r for r in results if r.member_id == member_id]
    assert len(matches) == 1, f"expected exactly one result for {member_id!r}, got {matches}"
    return matches[0]


# --- non-working day ---------------------------------------------------------


def test_skips_a_non_working_day_without_generating_anything(db_path):
    config = _config()
    publisher = _RecordingPublisher()

    results = run_escalation_job(config.channel_id, config, publisher, day=SATURDAY, db_path=db_path)

    assert len(results) == 1
    assert results[0].status == SKIPPED_NON_WORKING_DAY
    assert publisher.calls == []


# --- threshold-driven ---------------------------------------------------------


def test_below_threshold_produces_no_escalation_and_no_proposal(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    # alice contributes every day; dave is silent MON and TUE only (2
    # consecutive missed days -- below the threshold of 3).
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")

    results = run_escalation_job(config.channel_id, config, _RecordingPublisher(), day=TUE, db_path=db_path)

    dave_result = _result_for(results, "dave")
    assert dave_result.status == BELOW_THRESHOLD
    assert "2 consecutive working day" in dave_result.detail
    proposal_count = ProposalStore(db_path)
    assert proposal_count.get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}") is None


# --- never the excluded, checked twice, independently -------------------------


def test_excluded_member_is_never_escalated_via_the_real_ledger(db_path):
    """carol is never even a candidate here: build_ledger() already
    marks her EXCLUDED, and _eligible_candidates() filters EXCLUDED-
    state records out before run_escalation_job's own per-member loop
    ever runs -- so she produces no result at all, the same posture
    test_nudge_job.py's own real-ledger test asserts for an excepted
    member. The defensive test below is what proves the independent
    per-member check itself, using a deliberately mislabelled record."""
    config = _config()  # carol is on the exceptions list
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    publisher = _RecordingPublisher()

    results = run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)

    member_ids = {r.member_id for r in results}
    assert "carol" not in member_ids
    assert EscalationStore(db_path).has_ever_been_escalated("esc-channel", "carol") is False
    assert all(call[0] != "priya" or "carol" not in call[1] for call in publisher.calls)


def test_excluded_member_is_never_escalated_even_if_the_ledger_mislabels_them(db_path):
    """Defensive test: if build_ledger() itself were ever wrong and
    handed this job a NO_MESSAGE record for an excepted member on
    `day`, the job's own independent exceptions check must still
    refuse to escalate them -- exactly CHN-21's own bug-fix lesson,
    applied here from the start."""
    config = _config()
    mislabelled_records = [
        ParticipationRecord(
            channel_id=config.channel_id, member_id="carol", date=WED.isoformat(),
            state=NO_MESSAGE, evidence_message_ids=(),
        ),
    ]
    publisher = _RecordingPublisher()

    results = run_escalation_job(
        config.channel_id, config, publisher, day=WED, db_path=db_path, ledger_records=mislabelled_records,
    )

    assert len(results) == 1
    assert results[0].member_id == "carol"
    assert results[0].status == EXCLUDED_STATUS
    assert publisher.calls == []
    assert EscalationStore(db_path).has_ever_been_escalated("esc-channel", "carol") is False


# --- nudge precedes escalation -------------------------------------------------


def test_a_member_who_has_never_been_nudged_is_not_escalated_even_past_threshold(db_path):
    config = _config()
    # bob is silent MON/TUE/WED (3 consecutive days -- past the
    # threshold) but has never been nudged in this channel.
    _seed_anchor(db_path, "bob")
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    _seed_previously_nudged(db_path, "esc-channel", "dave")  # dave has -- for contrast
    _seed_anchor(db_path, "dave")
    publisher = _RecordingPublisher()

    results = run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)

    bob_result = _result_for(results, "bob")
    assert bob_result.status == AWAITING_NUDGE
    assert publisher.calls == [] or all(call[0] != "priya" for call in publisher.calls if "bob" in call[1])
    assert ProposalStore(db_path).get_by_idempotency_key(f"esc-channel:bob:{MON.isoformat()}") is None


# --- first escalation ever requires approval -----------------------------------


def test_first_escalation_ever_creates_a_pending_proposal_and_does_not_send(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    publisher = _RecordingPublisher()

    results = run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)

    dave_result = _result_for(results, "dave")
    assert dave_result.status == AWAITING_APPROVAL
    assert publisher.calls == []
    proposal = ProposalStore(db_path).get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}")
    assert proposal is not None
    assert proposal.status == PENDING
    assert proposal.payload["streak_start_date"] == MON.isoformat()
    assert proposal.payload["streak_end_date"] == WED.isoformat()
    assert [d["date"] for d in proposal.payload["days"]] == [MON.isoformat(), TUE.isoformat(), WED.isoformat()]


def test_reruns_before_approval_never_duplicate_the_proposal_or_send(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    publisher = _RecordingPublisher()

    for _ in range(3):
        results = run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
        assert _result_for(results, "dave").status == AWAITING_APPROVAL

    assert publisher.calls == []
    conn = get_connection(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE idempotency_key = ?",
            (f"esc-channel:dave:{MON.isoformat()}",),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert count == 1


def test_after_human_approval_a_rerun_sends_and_marks_applied(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    publisher = _RecordingPublisher()

    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}")
    proposal_store.approve(proposal.id, approver_id="priya")

    results = run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)

    dave_result = _result_for(results, "dave")
    assert dave_result.status == SENT
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] == "priya"  # sent to the OWNER, not to dave
    assert "dave" in publisher.calls[0][1]
    assert proposal_store.get(proposal.id).status == APPLIED
    assert EscalationStore(db_path).has_ever_been_escalated("esc-channel", "dave") is True


def test_a_rejected_escalation_never_sends_on_any_rerun(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    publisher = _RecordingPublisher()

    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}")
    proposal_store.reject(proposal.id, approver_id="priya")

    first = run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    second = run_escalation_job(config.channel_id, config, publisher, day=THU, db_path=db_path)

    assert _result_for(first, "dave").status == REJECTED_STATUS
    assert _result_for(second, "dave").status == REJECTED_STATUS
    assert publisher.calls == []


# --- the same continuous streak is never escalated twice -----------------------


def test_the_same_continuous_streak_is_never_escalated_twice(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    for d in (MON, TUE, WED):
        _seed_contributes(db_path, "alice", d, "m")
    publisher = _RecordingPublisher()

    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal_store.approve(
        proposal_store.get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}").id, approver_id="priya",
    )
    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    assert len(publisher.calls) == 1

    # dave is still silent on THU -- the streak is now 4 days long, but
    # its streak_start_date (MON) hasn't changed, so this must report
    # ALREADY_SENT, not a second escalation.
    _seed_contributes(db_path, "alice", THU, "m")
    results = run_escalation_job(config.channel_id, config, publisher, day=THU, db_path=db_path)

    assert _result_for(results, "dave").status == ALREADY_SENT
    assert len(publisher.calls) == 1  # never resent
    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM escalations WHERE member_id = 'dave'").fetchone()["n"]
    finally:
        conn.close()
    assert count == 1


def test_a_broken_streak_that_recurs_creates_a_new_escalation_and_auto_approves(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    for d in (MON, TUE, WED, THU):
        _seed_contributes(db_path, "alice", d, "m")
    publisher = _RecordingPublisher()

    # First streak: MON-WED silent, escalate and approve on WED.
    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal_store.approve(
        proposal_store.get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}").id, approver_id="priya",
    )
    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    assert len(publisher.calls) == 1
    assert EscalationStore(db_path).has_ever_been_escalated("esc-channel", "dave") is True

    # dave breaks the streak on THU and FRI by contributing.
    _seed_contributes(db_path, "dave", THU, "d")
    _seed_contributes(db_path, "dave", FRI, "d")
    run_escalation_job(config.channel_id, config, publisher, day=THU, db_path=db_path)
    run_escalation_job(config.channel_id, config, publisher, day=FRI, db_path=db_path)
    assert len(publisher.calls) == 1  # still just the one -- dave contributed both days

    # A new streak: dave is silent again MON2-WED2 (a fresh 3 consecutive
    # missed days, unrelated to the first streak). Since dave was already
    # escalated once before, this new streak's escalation must
    # auto-approve and send unattended, with no human in the loop.
    for d in (MON2, TUE2, WED2):
        _seed_contributes(db_path, "alice", d, "m")

    results = run_escalation_job(config.channel_id, config, publisher, day=WED2, db_path=db_path)

    dave_result = _result_for(results, "dave")
    assert dave_result.status == SENT
    assert len(publisher.calls) == 2
    new_proposal = proposal_store.get_by_idempotency_key(f"esc-channel:dave:{MON2.isoformat()}")
    assert new_proposal.approver_id == AUTO_APPROVE_APPROVER_ID
    assert new_proposal.status == APPLIED


# --- the evidence bundle carries dates, window, and per-day state -------------


def test_evidence_bundle_contains_dates_window_and_per_day_state(db_path):
    config = _config()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    # dave posts chatter (not an update) on TUE -- proves the bundle
    # distinguishes posted_no_update from no_message per day.
    _seed_message(db_path, "dave-tue", "dave", TUE, "chatter")
    publisher = _RecordingPublisher()

    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}")
    proposal_store.approve(proposal.id, approver_id="priya")
    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)

    days = proposal_store.get(proposal.id).payload["days"]
    assert days[0] == {"date": MON.isoformat(), "state": NO_MESSAGE, "evidence_message_ids": []}
    assert days[1] == {"date": TUE.isoformat(), "state": POSTED_NO_UPDATE, "evidence_message_ids": ["dave-tue"]}
    assert days[2] == {"date": WED.isoformat(), "state": NO_MESSAGE, "evidence_message_ids": []}

    content = publisher.calls[0][1]
    assert MON.isoformat() in content
    assert TUE.isoformat() in content
    assert WED.isoformat() in content
    assert "dave-tue" in content
    assert "09:00-11:00 UTC" in content


# --- the message names the person by their real display name, not their raw id -


def test_escalation_message_uses_the_members_display_name_not_the_raw_member_id(db_path):
    # 2026-09-21 fix (see DECISION_LOG.md): _render_escalation_message()
    # used to interpolate member_id directly -- this file's own db_path
    # fixture seeds every member with display_name == member_id, which
    # made that bug invisible to every other test above (the assertions
    # like "dave" in content pass either way). Here dave's real name is
    # set to something that does NOT equal his member_id, so only a
    # genuine members-table lookup can make this pass.
    config = _config()
    conn = get_connection(db_path)
    try:
        conn.execute("UPDATE members SET display_name = ? WHERE id = 'dave'", ("Dave Realname",))
        conn.commit()
    finally:
        conn.close()
    _seed_previously_nudged(db_path, "esc-channel", "dave")
    _seed_anchor(db_path, "dave")
    _seed_contributes(db_path, "alice", MON, "m")
    _seed_contributes(db_path, "alice", TUE, "m")
    _seed_contributes(db_path, "alice", WED, "m")
    publisher = _RecordingPublisher()

    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"esc-channel:dave:{MON.isoformat()}")
    proposal_store.approve(proposal.id, approver_id="priya")
    run_escalation_job(config.channel_id, config, publisher, day=WED, db_path=db_path)

    content = publisher.calls[0][1]
    assert content.startswith("Hi! Dave Realname has missed")
    assert "Dave Realname" in content
