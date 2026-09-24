"""
Same-day catch-up and the fixes around it (2026-09-24): a ~3 hour network
outage beat a 4-minute retry window, the digest went out hours late, and it
went out with the content frozen at 17:30 -- missing two updates posted after
the failed send. Covers: when a digest/weekly counts as overdue, that catch-up
never touches anything waiting on (or decided by) a human, that a retried
system-approved proposal carries current content while a human-approved one is
never rewritten, and that a failed send now keeps its reason.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from p1.approval.proposals import ProposalStore
from p1.config.schema import ChannelConfig
from p1.publishing.catchup import overdue_daily, overdue_weekly, run_missed_publishing
from p1.publishing.daily_job import AUTO_APPROVE_APPROVER_ID
from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore
from spine.approval.proposals import IllegalTransitionError

CH = "catchup-channel"
TZ = ZoneInfo("Asia/Colombo")
THURSDAY = date(2026, 9, 24)   # working day; daily digest 17:30
FRIDAY = date(2026, 9, 25)     # weekly roll-up day, 17:45


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CH, "display_name": "Catchup Channel", "roster": ["alice"],
        "update_window_start": time(8, 0), "update_window_end": time(17, 30),
        "timezone": "Asia/Colombo", "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "daily_digest_time": time(17, 30), "weekly_digest_day": "Fri", "weekly_digest_time": time(17, 45),
        "channel_owner_id": "alice",
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'C', 1)", (CH,))
    conn.commit()
    conn.close()
    return path


def at(day: date, hh: int, mm: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)


def _proposal(db_path, key, *, approve_as=None, reject=False):
    store = ProposalStore(db_path)
    p = store.create(type="daily_digest_publish", payload={"content": "x"}, original_model_output={"content": "x"},
                     source_refs=[], idempotency_key=key)
    if approve_as:
        p = store.approve(p.id, approver_id=approve_as)
    if reject:
        p = store.reject(p.id, approver_id="human")
    return p


# --- when is the daily digest overdue? -----------------------------------------

def test_not_overdue_before_the_scheduled_time_plus_grace(db_path):
    assert overdue_daily(_config(), at(THURSDAY, 17, 39), db_path=db_path) is False  # 9 min after 17:30


def test_overdue_once_past_the_grace_window_with_nothing_sent(db_path):
    assert overdue_daily(_config(), at(THURSDAY, 17, 40), db_path=db_path) is True
    assert overdue_daily(_config(), at(THURSDAY, 22, 0), db_path=db_path) is True


def test_not_overdue_once_published(db_path):
    d = DigestStore(db_path)
    d.record(channel_id=CH, date=THURSDAY.isoformat(), type="daily", content="x", idempotency_key=f"{CH}:{THURSDAY}:daily")
    d.mark_published(idempotency_key=f"{CH}:{THURSDAY}:daily", published_at="2026-09-24T12:00:00+00:00")
    assert overdue_daily(_config(), at(THURSDAY, 22, 0), db_path=db_path) is False


def test_an_approved_but_unsent_proposal_is_overdue_this_is_the_failed_send_case(db_path):
    _proposal(db_path, f"{CH}:{THURSDAY}:daily_publish", approve_as=AUTO_APPROVE_APPROVER_ID)
    assert overdue_daily(_config(), at(THURSDAY, 20, 0), db_path=db_path) is True


def test_a_pending_proposal_waiting_for_a_human_is_never_caught_up(db_path):
    _proposal(db_path, f"{CH}:{THURSDAY}:daily_publish")
    assert overdue_daily(_config(), at(THURSDAY, 20, 0), db_path=db_path) is False


def test_a_rejected_proposal_is_never_caught_up(db_path):
    _proposal(db_path, f"{CH}:{THURSDAY}:daily_publish", reject=True)
    assert overdue_daily(_config(), at(THURSDAY, 20, 0), db_path=db_path) is False


def test_never_overdue_on_a_non_working_day_or_for_yesterdays_digest(db_path):
    saturday = date(2026, 9, 26)
    assert overdue_daily(_config(), at(saturday, 20, 0), db_path=db_path) is False
    # Thursday's digest was never sent, but it is now Friday 09:00 and 17:30 has not
    # yet come round: catch-up looks at TODAY only.
    assert overdue_daily(_config(), at(FRIDAY, 9, 0), db_path=db_path) is False


# --- weekly ----------------------------------------------------------------------

def test_weekly_overdue_only_on_its_day_after_its_time(db_path):
    assert overdue_weekly(_config(), at(FRIDAY, 17, 50), db_path=db_path) is False  # inside grace
    assert overdue_weekly(_config(), at(FRIDAY, 18, 0), db_path=db_path) is True
    assert overdue_weekly(_config(), at(THURSDAY, 18, 0), db_path=db_path) is False  # wrong day


def test_the_first_weekly_ever_pending_approval_is_left_alone(db_path):
    _proposal(db_path, f"{CH}:{FRIDAY}:weekly_publish")
    assert overdue_weekly(_config(), at(FRIDAY, 20, 0), db_path=db_path) is False


# --- acting on it ----------------------------------------------------------------

def test_run_missed_publishing_runs_only_what_is_overdue(db_path):
    calls = []
    fake = lambda name: (lambda **kw: calls.append(name) or type("R", (), {"date": "d", "status": "published", "detail": ""})())

    ran = run_missed_publishing(_config(), None, None, db_path=db_path, now=at(THURSDAY, 20, 0),
                                daily_job=fake("daily"), weekly_job=fake("weekly"))
    assert calls == ["daily"] and [k for k, _ in ran] == ["digest"]

    calls.clear()
    ran = run_missed_publishing(_config(), None, None, db_path=db_path, now=at(THURSDAY, 12, 0),
                                daily_job=fake("daily"), weekly_job=fake("weekly"))
    assert calls == [] and ran == []


# --- a retried system-approved proposal carries current content -------------------

def test_a_system_approved_unsent_proposal_may_be_refreshed_before_resend(db_path):
    p = _proposal(db_path, "k1", approve_as=AUTO_APPROVE_APPROVER_ID)
    store = ProposalStore(db_path)
    refreshed = store.refresh_payload(p.id, payload={"content": "fresh"}, also_if_approved_by=AUTO_APPROVE_APPROVER_ID)
    assert refreshed.payload["content"] == "fresh"
    assert refreshed.original_model_output["content"] == "x"  # the original stays readable


def test_a_human_approved_proposal_is_never_rewritten(db_path):
    p = _proposal(db_path, "k2", approve_as="alice@example.com")
    with pytest.raises(IllegalTransitionError):
        ProposalStore(db_path).refresh_payload(
            p.id, payload={"content": "fresh"}, also_if_approved_by=AUTO_APPROVE_APPROVER_ID,
        )
    assert ProposalStore(db_path).get(p.id).payload["content"] == "x"


def test_a_sent_proposal_is_never_rewritten(db_path):
    p = _proposal(db_path, "k3", approve_as=AUTO_APPROVE_APPROVER_ID)
    store = ProposalStore(db_path)
    store.apply(p.id)
    with pytest.raises(IllegalTransitionError):
        store.refresh_payload(p.id, payload={"content": "fresh"}, also_if_approved_by=AUTO_APPROVE_APPROVER_ID)


def test_refresh_without_the_system_approver_still_refuses_an_approved_proposal(db_path):
    p = _proposal(db_path, "k4", approve_as=AUTO_APPROVE_APPROVER_ID)
    with pytest.raises(IllegalTransitionError):
        ProposalStore(db_path).refresh_payload(p.id, payload={"content": "fresh"})  # the original rule


# --- a failed send keeps its reason ------------------------------------------------

def test_a_failed_send_records_why(db_path):
    from spine.approval.write_guard import guarded_send

    p = _proposal(db_path, "k5", approve_as=AUTO_APPROVE_APPROVER_ID)

    def boom():
        raise ConnectionError("Failed to resolve 'hooks.example.com'")

    with pytest.raises(ConnectionError):
        guarded_send(p.id, action_type="channel_post", target=CH, send_fn=boom,
                     store=ProposalStore(db_path), db_path=db_path)
    conn = get_connection(db_path)
    row = conn.execute("SELECT status, payload FROM write_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    assert row["status"] == "send_failed"
    assert "ConnectionError" in json.loads(row["payload"])["error"]
    assert "Failed to resolve" in json.loads(row["payload"])["error"]


# --- the optional `before` hook (fresh data before publishing) ---------------------------

def test_before_runs_once_and_before_the_job_when_something_is_overdue(db_path):
    order = []
    job = lambda **kw: order.append("job") or type("R", (), {"date": "d", "status": "published", "detail": ""})()
    run_missed_publishing(_config(), None, None, db_path=db_path, now=at(THURSDAY, 20, 0),
                          daily_job=job, weekly_job=job, before=lambda: order.append("before"))
    assert order == ["before", "job"]


def test_before_is_not_run_when_nothing_is_overdue(db_path):
    calls = []
    run_missed_publishing(_config(), None, None, db_path=db_path, now=at(THURSDAY, 12, 0),
                          before=lambda: calls.append(1))
    assert calls == []


def test_if_before_fails_nothing_is_published_this_tick(db_path):
    ran = []

    def down():
        raise ConnectionError("no internet")

    with pytest.raises(ConnectionError):
        run_missed_publishing(_config(), None, None, db_path=db_path, now=at(THURSDAY, 20, 0),
                              daily_job=lambda **kw: ran.append(1), weekly_job=lambda **kw: ran.append(1), before=down)
    assert ran == []
