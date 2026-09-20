"""
CHN-17's own acceptance test: "A clock-override run at three different
channel-local times produces three correctly timed digests and no
duplicates" (test_three_channels_at_three_local_times_...). The rest of
this file walks run_daily_digest_job's full status-machine branching --
skip on a non-working day, first-publish-requires-approval, a rerun
before approval never re-proposes or sends, a rejected publish never
sends on any rerun, an approved publish actually sends and marks
applied, and subsequent days auto-approve and run unattended -- since
every one of those branches has to get the "no duplicate send" promise
right independently, not just the headline three-timezones case.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from p1.approval.proposals import APPLIED, APPROVED, PENDING, ProposalStore
from p1.config.schema import ChannelConfig
from p1.publishing.daily_job import (
    ALREADY_PUBLISHED,
    AUTO_APPROVE_APPROVER_ID,
    AWAITING_APPROVAL,
    PUBLISHED,
    REJECTED_STATUS,
    SKIPPED_NON_WORKING_DAY,
    run_daily_digest_job,
)
from p1.publishing.scheduler import is_due
from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore

DAY1 = date(2026, 6, 1)  # Monday
DAY2 = date(2026, 6, 2)  # Tuesday
SATURDAY = date(2026, 6, 6)


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "job-channel",
        "display_name": "Job Test Channel",
        "roster": ["alice"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": "UTC",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "non_working_dates": [],
        "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def _seed_channel(db_path: str, channel_id: str) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)",
            (channel_id, channel_id),
        )
        conn.commit()
    finally:
        conn.close()


class _NeverCalledGateway:
    """A channel with zero seeded messages has empty facts in every
    section, so generate_daily_summary must never call the model at
    all -- this stands in for the gateway and fails the test loudly if
    that ever stops being true."""

    def generate(self, *args, **kwargs):
        raise AssertionError("gateway.generate() must not be called for a channel with no messages")


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        self.calls.append((channel_id, content))
        return {"ok": True}


def _run(channel_id, config, day, db_path, publisher=None):
    return run_daily_digest_job(
        channel_id, config, gateway=_NeverCalledGateway(), publisher=publisher or _RecordingPublisher(),
        day=day, db_path=db_path,
    )


def _digest_row_count(db_path, channel_id):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM digests WHERE channel_id = ?", (channel_id,)
        ).fetchone()["n"]
    finally:
        conn.close()


def _proposal_row_count(db_path, idempotency_key):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM proposals WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()["n"]
    finally:
        conn.close()


# --- CHN-17's own acceptance test ------------------------------------------


def test_three_channels_at_three_local_times_produce_three_correctly_timed_digests_with_no_duplicates(db_path):
    configs = {
        "tokyo": _config(channel_id="tokyo", timezone="Asia/Tokyo", daily_digest_time=time(9, 0)),
        "london": _config(channel_id="london", timezone="Europe/London", daily_digest_time=time(9, 0)),
        "nyc": _config(channel_id="nyc", timezone="America/New_York", daily_digest_time=time(9, 0)),
    }
    for channel_id in configs:
        _seed_channel(db_path, channel_id)

    # The same shared wall-clock wish ("09:00, local") lands on three
    # different absolute UTC instants -- summer-time offsets as of
    # 2026-06-01: JST is UTC+9 (no DST), BST is UTC+1, EDT is UTC-4.
    due_moments = {
        "tokyo": datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc),
        "london": datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc),
        "nyc": datetime(2026, 6, 1, 13, 0, tzinfo=timezone.utc),
    }

    def _due_day(channel_id: str) -> date:
        config = configs[channel_id]
        return due_moments[channel_id].astimezone(ZoneInfo(config.timezone)).date()

    results = {}
    for channel_id, moment in due_moments.items():
        config = configs[channel_id]

        # Each channel is due at its own moment, and only its own.
        assert is_due(config, moment) is True
        for other_id, other_moment in due_moments.items():
            if other_id != channel_id:
                assert is_due(config, other_moment) is False

        local_day = _due_day(channel_id)
        assert local_day == DAY1  # same local calendar date for all three

        results[channel_id] = _run(channel_id, config, local_day, db_path)

    for channel_id, result in results.items():
        assert result.channel_id == channel_id
        assert result.date == DAY1.isoformat()
        # Fresh channels: each one's very first due day awaits approval,
        # never sends by itself.
        assert result.status == AWAITING_APPROVAL
        assert DigestStore(db_path).get_by_idempotency_key(f"{channel_id}:{DAY1.isoformat()}:daily") is not None

    # Firing again at each channel's own due moment (an overlapping or
    # retried cron tick) must not duplicate anything for any channel.
    for channel_id in due_moments:
        config = configs[channel_id]
        local_day = _due_day(channel_id)
        rerun = _run(channel_id, config, local_day, db_path)
        assert rerun.status == AWAITING_APPROVAL

        assert _digest_row_count(db_path, channel_id) == 1
        assert _proposal_row_count(db_path, f"{channel_id}:{DAY1.isoformat()}:daily_publish") == 1


# --- non-working days -------------------------------------------------------


def test_skips_a_non_working_day_without_generating_anything(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)

    result = _run(config.channel_id, config, SATURDAY, db_path)

    assert result.status == SKIPPED_NON_WORKING_DAY
    assert _digest_row_count(db_path, config.channel_id) == 0


# --- first publish requires approval ----------------------------------------


def test_first_publish_ever_creates_a_pending_proposal_and_does_not_send(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    result = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)

    assert result.status == AWAITING_APPROVAL
    assert publisher.calls == []
    proposal = ProposalStore(db_path).get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily_publish")
    assert proposal is not None
    assert proposal.status == PENDING


def test_a_rerun_before_approval_does_not_duplicate_the_proposal_or_send(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    second = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)

    assert second.status == AWAITING_APPROVAL
    assert publisher.calls == []
    assert _proposal_row_count(db_path, f"{config.channel_id}:{DAY1.isoformat()}:daily_publish") == 1


def test_after_human_approval_a_rerun_sends_and_marks_applied(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily_publish")
    proposal_store.approve(proposal.id, approver_id="priya")

    result = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)

    assert result.status == PUBLISHED
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] == config.channel_id
    assert proposal_store.get(proposal.id).status == APPLIED
    digest_row = DigestStore(db_path).get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily")
    assert digest_row["published_at"] is not None


def test_a_rejected_first_publish_never_sends_on_any_rerun(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily_publish")
    proposal_store.reject(proposal.id, approver_id="priya")

    result = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    result_again = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)

    assert result.status == REJECTED_STATUS
    assert result_again.status == REJECTED_STATUS
    assert publisher.calls == []


def test_calling_again_after_publish_reports_already_published_and_does_not_resend(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily_publish")
    proposal_store.approve(proposal.id, approver_id="priya")
    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)

    result = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)

    assert result.status == ALREADY_PUBLISHED
    assert len(publisher.calls) == 1  # still just the one real send


# --- a still-pending proposal's payload tracks digest regeneration ---------


def test_a_rerun_before_approval_refreshes_the_pending_proposals_payload(db_path, monkeypatch):
    """CHN-32-adjacent finding, 2026-09-19: a real first-publish proposal
    sat pending for hours while new Teams messages arrived; every rerun
    regenerated the digests table's own content but left this proposal
    -- the thing guarded_send() actually posts -- frozen at its
    creation-time snapshot. Isolating from the real digest-generation
    pipeline (as _NeverCalledGateway already does for the no-messages
    case) by faking generate_and_persist_daily_summary directly, since
    what changed is daily_job.py's own handling of an existing pending
    proposal, not digest generation itself.
    """
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    contents = ["draft one -- nothing happened yet", "draft two -- a message arrived since"]
    call_count = {"n": 0}

    class _FakeDigestResult:
        def __init__(self, content):
            self.content = content
            self.section_lines = {}

    def _fake_generate_and_persist(*args, **kwargs):
        # Regeneration happens on every call by design (this function's
        # own module docstring), including the post-approval rerun that
        # actually triggers the send -- so once the queued drafts run
        # out, keep returning the last one rather than raising
        # StopIteration, exactly like a real unchanged channel would
        # regenerate the same content again.
        idx = min(call_count["n"], len(contents) - 1)
        call_count["n"] += 1
        return _FakeDigestResult(contents[idx])

    import p1.publishing.daily_job as daily_job_module

    monkeypatch.setattr(daily_job_module, "generate_and_persist_daily_summary", _fake_generate_and_persist)

    first = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    assert first.status == AWAITING_APPROVAL
    proposal_store = ProposalStore(db_path)
    key = f"{config.channel_id}:{DAY1.isoformat()}:daily_publish"
    proposal_before = proposal_store.get_by_idempotency_key(key)
    assert proposal_before.payload["content"] == "draft one -- nothing happened yet"

    second = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    assert second.status == AWAITING_APPROVAL
    assert publisher.calls == []  # still never sends while pending
    assert _proposal_row_count(db_path, key) == 1  # refreshed in place, not duplicated

    proposal_after = proposal_store.get_by_idempotency_key(key)
    assert proposal_after.id == proposal_before.id
    assert proposal_after.payload["content"] == "draft two -- a message arrived since"

    # Approving and sending now must post the REFRESHED content, not
    # the stale snapshot from the moment this proposal was created.
    proposal_store.approve(proposal_after.id, approver_id="priya")
    third = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    assert third.status == PUBLISHED
    assert publisher.calls[-1][1] == "draft two -- a message arrived since"


def test_after_approval_a_rerun_never_touches_the_proposals_payload_again(db_path, monkeypatch):
    """The safety half of the same fix: refresh_payload() is reachable
    only through the `elif proposal.status == PENDING` branch, so once a
    human has approved (or rejected, or it's been applied), a later
    rerun -- even one where digest generation would produce different
    content -- must never rewrite what was actually decided."""
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    contents = iter(["draft one -- approved on this content", "draft two -- must never appear"])

    class _FakeDigestResult:
        def __init__(self, content):
            self.content = content
            self.section_lines = {}

    def _fake_generate_and_persist(*args, **kwargs):
        return _FakeDigestResult(next(contents))

    import p1.publishing.daily_job as daily_job_module

    monkeypatch.setattr(daily_job_module, "generate_and_persist_daily_summary", _fake_generate_and_persist)

    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    proposal_store = ProposalStore(db_path)
    key = f"{config.channel_id}:{DAY1.isoformat()}:daily_publish"
    proposal = proposal_store.get_by_idempotency_key(key)
    proposal_store.approve(proposal.id, approver_id="priya")

    result = _run(config.channel_id, config, DAY1, db_path, publisher=publisher)

    assert result.status == PUBLISHED
    assert publisher.calls[-1][1] == "draft one -- approved on this content"
    assert proposal_store.get(proposal.id).payload["content"] == "draft one -- approved on this content"


# --- subsequent days run unattended -----------------------------------------


def test_subsequent_days_auto_approve_and_send_unattended(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)
    publisher = _RecordingPublisher()

    # Day 1: first publish ever -- awaits a human, as proven above.
    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    proposal_store = ProposalStore(db_path)
    day1_proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily_publish")
    proposal_store.approve(day1_proposal.id, approver_id="priya")
    _run(config.channel_id, config, DAY1, db_path, publisher=publisher)
    assert DigestStore(db_path).has_ever_published(config.channel_id) is True

    # Day 2: nobody approves anything -- the job itself must auto-approve
    # and send in the same run.
    result = _run(config.channel_id, config, DAY2, db_path, publisher=publisher)

    assert result.status == PUBLISHED
    assert len(publisher.calls) == 2
    day2_proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:{DAY2.isoformat()}:daily_publish")
    assert day2_proposal.approver_id == AUTO_APPROVE_APPROVER_ID
    assert day2_proposal.status == APPLIED


def test_a_send_failure_is_not_silently_swallowed_and_proposal_stays_approved(db_path):
    config = _config()
    _seed_channel(db_path, config.channel_id)

    class _FailingPublisher:
        def post_channel_message(self, channel_id, content):
            raise RuntimeError("publish adapter is down")

    _run(config.channel_id, config, DAY1, db_path, publisher=_RecordingPublisher())
    proposal_store = ProposalStore(db_path)
    proposal = proposal_store.get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily_publish")
    proposal_store.approve(proposal.id, approver_id="priya")

    with pytest.raises(RuntimeError, match="publish adapter is down"):
        _run(config.channel_id, config, DAY1, db_path, publisher=_FailingPublisher())

    assert proposal_store.get(proposal.id).status == APPROVED
    digest_row = DigestStore(db_path).get_by_idempotency_key(f"{config.channel_id}:{DAY1.isoformat()}:daily")
    assert digest_row["published_at"] is None
