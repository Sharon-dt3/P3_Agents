"""
Scheduled publishing of the weekly roll-up (run_weekly_rollup_job and its
schedule wiring). Walks the same status machine test_daily_job.py walks for
the daily digest -- first-ever weekly needs a human, a rerun never
duplicates or sends, a rejection never sends, an approved one sends exactly
once, later weeks run unattended -- plus the one rule that is new here: the
"first ever" question is asked per digest TYPE, so a channel with a long
history of published DAILY digests still holds its first WEEKLY roll-up for
a human. Also proves the schedule itself: the job fires on the channel's
weekly_digest_day at weekly_digest_time in its own timezone, and
add_weekly_rollup_jobs() adds it to a scheduler that already has other jobs.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from p1.approval.proposals import APPLIED, ProposalStore
from p1.config.schema import ChannelConfig
from p1.llm.gateway import LLMResponse
from p1.publishing.daily_job import (
    ALREADY_PUBLISHED,
    AWAITING_APPROVAL,
    PUBLISHED,
    REJECTED_STATUS,
    SKIPPED_NON_WORKING_DAY,
)
from p1.publishing.scheduler import add_weekly_rollup_jobs, is_weekly_due
from p1.publishing.weekly_job import run_weekly_rollup_job
from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore

CHANNEL_ID = "weekly-job-channel"
FRIDAY1 = date(2026, 6, 5)
FRIDAY2 = date(2026, 6, 12)


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID,
        "display_name": "Weekly Job Channel",
        "roster": ["alice"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": "Asia/Colombo",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "non_working_dates": [],
        "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


class _Gateway:
    """Always returns a valid, digit-free narrative -- the weekly roll-up
    always makes exactly one model call, unlike an empty daily digest."""

    def generate(self, prompt, **kwargs):
        return LLMResponse(
            text=json.dumps({"narrative": "A quiet week with steady progress."}),
            provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


class _Publisher:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        self.calls.append((channel_id, content))
        return {"ok": True}


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)", (CHANNEL_ID, "W"))
    conn.execute("INSERT INTO members (id, display_name) VALUES ('alice', 'Alice Example')")
    conn.commit()
    conn.close()
    return path


def _run(db_path, week_end, publisher, config=None):
    return run_weekly_rollup_job(
        CHANNEL_ID, config or _config(), _Gateway(), publisher, week_end=week_end, db_path=db_path,
    )


# --- publishing: the status machine ---------------------------------------------

def test_the_first_weekly_rollup_ever_waits_for_a_human_and_sends_nothing(db_path):
    publisher = _Publisher()
    result = _run(db_path, FRIDAY1, publisher)
    assert result.status == AWAITING_APPROVAL
    assert publisher.calls == []


def test_first_weekly_is_held_even_when_the_channel_already_published_daily_digests(db_path):
    """The per-type rule: a published DAILY digest must not count as
    'this channel has had a weekly roll-up before'."""
    digests = DigestStore(db_path)
    digests.record(channel_id=CHANNEL_ID, date="2026-06-04", type="daily", content="x",
                   idempotency_key=f"{CHANNEL_ID}:2026-06-04:daily")
    digests.mark_published(idempotency_key=f"{CHANNEL_ID}:2026-06-04:daily", published_at="2026-06-04T12:00:00+00:00")
    assert digests.has_ever_published(CHANNEL_ID) is True
    assert digests.has_ever_published_type(CHANNEL_ID, "weekly") is False

    publisher = _Publisher()
    assert _run(db_path, FRIDAY1, publisher).status == AWAITING_APPROVAL
    assert publisher.calls == []


def test_rerunning_before_approval_never_duplicates_the_proposal_or_sends(db_path):
    publisher = _Publisher()
    for _ in range(3):
        assert _run(db_path, FRIDAY1, publisher).status == AWAITING_APPROVAL
    conn = get_connection(db_path)
    n = conn.execute("SELECT COUNT(*) AS n FROM proposals WHERE idempotency_key = ?",
                     (f"{CHANNEL_ID}:{FRIDAY1.isoformat()}:weekly_publish",)).fetchone()["n"]
    conn.close()
    assert n == 1
    assert publisher.calls == []


def test_an_approved_weekly_sends_exactly_once_across_reruns(db_path):
    publisher = _Publisher()
    _run(db_path, FRIDAY1, publisher)
    store = ProposalStore(db_path)
    proposal = store.get_by_idempotency_key(f"{CHANNEL_ID}:{FRIDAY1.isoformat()}:weekly_publish")
    store.approve(proposal.id, approver_id="test:human")

    assert _run(db_path, FRIDAY1, publisher).status == PUBLISHED
    assert _run(db_path, FRIDAY1, publisher).status == ALREADY_PUBLISHED
    assert _run(db_path, FRIDAY1, publisher).status == ALREADY_PUBLISHED
    assert len(publisher.calls) == 1
    assert publisher.calls[0][0] == CHANNEL_ID
    assert "Weekly Roll-up" in publisher.calls[0][1]
    assert store.get(proposal.id).status == APPLIED
    assert DigestStore(db_path).has_ever_published_type(CHANNEL_ID, "weekly") is True


def test_a_rejected_weekly_never_sends_on_any_rerun(db_path):
    publisher = _Publisher()
    _run(db_path, FRIDAY1, publisher)
    store = ProposalStore(db_path)
    proposal = store.get_by_idempotency_key(f"{CHANNEL_ID}:{FRIDAY1.isoformat()}:weekly_publish")
    store.reject(proposal.id, approver_id="test:human")

    for _ in range(2):
        assert _run(db_path, FRIDAY1, publisher).status == REJECTED_STATUS
    assert publisher.calls == []


def test_later_weeks_auto_approve_and_send_unattended(db_path):
    publisher = _Publisher()
    _run(db_path, FRIDAY1, publisher)
    store = ProposalStore(db_path)
    store.approve(store.get_by_idempotency_key(f"{CHANNEL_ID}:{FRIDAY1.isoformat()}:weekly_publish").id,
                  approver_id="test:human")
    assert _run(db_path, FRIDAY1, publisher).status == PUBLISHED

    assert _run(db_path, FRIDAY2, publisher).status == PUBLISHED  # no human step this time
    assert len(publisher.calls) == 2


def test_a_configured_non_working_week_end_date_is_skipped(db_path):
    publisher = _Publisher()
    config = _config(non_working_dates=[FRIDAY1])
    assert _run(db_path, FRIDAY1, publisher, config).status == SKIPPED_NON_WORKING_DAY
    assert publisher.calls == []


# --- the schedule ------------------------------------------------------------------

def test_is_weekly_due_only_on_the_configured_day_and_time_in_the_channels_own_timezone():
    config = _config()  # Fri 16:00 Asia/Colombo (UTC+05:30)
    colombo = ZoneInfo("Asia/Colombo")
    assert is_weekly_due(config, datetime(2026, 6, 5, 16, 0, tzinfo=colombo)) is True
    assert is_weekly_due(config, datetime(2026, 6, 5, 10, 30, tzinfo=ZoneInfo("UTC"))) is True  # same instant
    assert is_weekly_due(config, datetime(2026, 6, 5, 16, 1, tzinfo=colombo)) is False   # wrong minute
    assert is_weekly_due(config, datetime(2026, 6, 4, 16, 0, tzinfo=colombo)) is False   # Thursday
    assert is_weekly_due(config, datetime(2026, 6, 5, 9, 0, tzinfo=colombo)) is False    # the daily time, not weekly


def test_weekly_job_is_added_to_an_existing_scheduler_with_the_right_trigger(db_path):
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: None, "interval", minutes=5, id="ingest:existing")

    add_weekly_rollup_jobs(scheduler, [_config()], _Gateway(), _Publisher(), db_path=db_path)

    jobs = {job.id: job for job in scheduler.get_jobs()}
    assert set(jobs) == {"ingest:existing", f"weekly_rollup:{CHANNEL_ID}"}
    weekly = jobs[f"weekly_rollup:{CHANNEL_ID}"]
    fields = {f.name: str(f) for f in weekly.trigger.fields}
    assert fields["day_of_week"] == "fri"
    assert (fields["hour"], fields["minute"]) == ("16", "0")
    assert str(weekly.trigger.timezone) == "Asia/Colombo"
    assert weekly.misfire_grace_time == 6 * 3600
    assert weekly.kwargs["channel_id"] == CHANNEL_ID
