"""
Direct unit tests for CHN-19's fact-gathering layer
(p1.reporting.weekly_facts) -- one focused scenario per function,
each small enough that the expected numbers are obvious by inspection,
distinct from test_weekly_summary.py's own larger end-to-end scenario
which independently hand-recomputes every figure against the same raw
seed data (this row's own acceptance test).
"""

from __future__ import annotations

from datetime import date, time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.reporting.weekly_facts import (
    gather_weekly_facts,
    member_participation,
    participation_trend,
    recurring_blockers,
    unanswered_all_week_questions,
    week_bounds,
    weekly_decisions,
    working_days_in_range,
)
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

CHANNEL_ID = "wk-channel"
TZ = "UTC"
# 2026-06-01 is a Monday (established elsewhere in this repo's own tests).
WEEK_END = date(2026, 6, 5)  # Friday
WEEK_START = date(2026, 5, 30)  # Saturday -- week_bounds' own 7-day window


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID,
        "display_name": "Weekly Test Channel",
        "allowlisted": True,
        "roster": ["alice", "bob"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": TZ,
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "non_working_dates": [],
        "length_floor": 10,
        "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
        "exceptions": [],
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)", (CHANNEL_ID, "C"))
    for member_id in ("alice", "bob"):
        conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
    conn.commit()
    conn.close()
    return path


def _seed(db_path, message_id, author_id, day, label, *, body="text", thread_root_id=None):
    MessageStore(db_path).upsert_messages(
        [
            TeamsMessage(
                id=message_id, channel_id=CHANNEL_ID, author_id=author_id, thread_root_id=thread_root_id,
                posted_at=f"{day.isoformat()}T09:00:00+00:00", body=body,
                permalink=f"https://teams.microsoft.com/l/message/{CHANNEL_ID}/{message_id}",
            )
        ]
    )
    ClassificationStore(db_path).record(message_id=message_id, label=label, method="model", confidence=0.9)


# --- week_bounds / working_days_in_range ------------------------------


def test_week_bounds_is_a_seven_day_window_ending_inclusive():
    assert week_bounds(WEEK_END) == (WEEK_START, WEEK_END)


def test_working_days_in_range_excludes_weekends_and_non_working_dates():
    config = _config(non_working_dates=[date(2026, 6, 2)])  # Tuesday off
    days = working_days_in_range(WEEK_START, WEEK_END, config)
    assert days == [date(2026, 6, 1), date(2026, 6, 3), date(2026, 6, 4), date(2026, 6, 5)]


# --- member_participation -----------------------------------------------


def test_member_contributing_two_of_five_working_days(db_path):
    _seed(db_path, "m1", "alice", date(2026, 6, 1), "update")
    _seed(db_path, "m2", "alice", date(2026, 6, 2), "update")
    result = member_participation(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert result["alice"].working_days == 5
    assert result["alice"].contributed_days == 2
    assert result["alice"].rate == pytest.approx(0.4)


def test_member_with_only_chatter_does_not_contribute(db_path):
    _seed(db_path, "m1", "bob", date(2026, 6, 1), "chatter")
    result = member_participation(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert result["bob"].contributed_days == 0
    assert result["bob"].rate == 0.0


def test_excepted_member_is_absent_from_participation_entirely(db_path):
    config = _config(exceptions=[{"member_id": "bob", "reason": "On leave"}])
    result = member_participation(CHANNEL_ID, WEEK_END, config, db_path=db_path)
    assert "bob" not in result
    assert "alice" in result


def test_two_messages_same_day_count_as_one_contributed_day(db_path):
    _seed(db_path, "m1", "alice", date(2026, 6, 1), "update")
    _seed(db_path, "m2", "alice", date(2026, 6, 1), "blocker")
    result = member_participation(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert result["alice"].contributed_days == 1


# --- participation_trend -------------------------------------------------


def test_trend_delta_is_current_minus_prior(db_path):
    # Prior week (2026-05-23..05-29): alice contributes 1 of 5 days.
    _seed(db_path, "prior-1", "alice", date(2026, 5, 25), "update")
    # Current week: alice contributes 3 of 5 days.
    _seed(db_path, "cur-1", "alice", date(2026, 6, 1), "update")
    _seed(db_path, "cur-2", "alice", date(2026, 6, 2), "update")
    _seed(db_path, "cur-3", "alice", date(2026, 6, 3), "update")

    trend = participation_trend(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)["alice"]
    assert trend.prior.rate == pytest.approx(0.2)
    assert trend.current.rate == pytest.approx(0.6)
    assert trend.delta == pytest.approx(0.4)


def test_trend_delta_is_none_when_prior_week_has_zero_working_days(db_path):
    """An edge case reachable only via config, not seed data: a channel
    whose entire prior-week window is non-working (e.g. the channel was
    on a company-wide shutdown that week). Delta is undefined, not 0,
    when there is nothing to compare against."""
    from datetime import timedelta

    prior_week_days = [date(2026, 5, 23) + timedelta(days=i) for i in range(7)]
    config = _config(non_working_dates=prior_week_days)
    trend = participation_trend(CHANNEL_ID, WEEK_END, config, db_path=db_path)["alice"]
    assert trend.prior.working_days == 0
    assert trend.prior.rate is None
    assert trend.delta is None


# --- recurring_blockers ---------------------------------------------------


def test_two_distinct_days_is_recurring(db_path):
    _seed(db_path, "b1", "bob", date(2026, 6, 1), "blocker")
    _seed(db_path, "b2", "bob", date(2026, 6, 3), "blocker")
    result = recurring_blockers(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert len(result) == 1
    assert result[0].author_id == "bob"
    assert result[0].message_ids == ("b1", "b2")
    assert result[0].days == ("2026-06-01", "2026-06-03")


def test_a_single_day_blocker_is_not_recurring(db_path):
    _seed(db_path, "b1", "alice", date(2026, 6, 2), "blocker")
    result = recurring_blockers(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert result == []


def test_two_same_day_blockers_are_not_recurring(db_path):
    _seed(db_path, "b1", "alice", date(2026, 6, 2), "blocker")
    _seed(db_path, "b2", "alice", date(2026, 6, 2), "blocker")
    result = recurring_blockers(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert result == []


def test_a_prior_week_recurring_pattern_does_not_leak_into_the_current_week(db_path):
    _seed(db_path, "p1", "bob", date(2026, 5, 25), "blocker")
    _seed(db_path, "p2", "bob", date(2026, 5, 27), "blocker")
    result = recurring_blockers(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert result == []


# --- weekly_decisions -----------------------------------------------------


def test_weekly_decisions_lists_decisions_within_the_window(db_path):
    _seed(db_path, "d1", "alice", date(2026, 6, 4), "decision", body="We decided to ship Friday.")
    _seed(db_path, "d2", "alice", date(2026, 5, 28), "decision", body="Prior week decision, out of window.")
    result = weekly_decisions(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert [f.message_id for f in result] == ["d1"]
    assert result[0].body_raw == "We decided to ship Friday."


# --- unanswered_all_week_questions ----------------------------------------


def test_a_question_answered_within_the_week_is_excluded(db_path):
    _seed(db_path, "q1", "bob", date(2026, 6, 1), "question")
    _seed(db_path, "q1-reply", "alice", date(2026, 6, 2), "chatter", thread_root_id="q1")
    result = unanswered_all_week_questions(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert result == []


def test_a_question_with_no_reply_at_all_is_unanswered(db_path):
    _seed(db_path, "q2", "alice", date(2026, 6, 4), "question")
    result = unanswered_all_week_questions(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert [f.message_id for f in result] == ["q2"]


def test_a_reply_that_arrives_the_following_week_does_not_count(db_path):
    _seed(db_path, "q3", "bob", date(2026, 6, 5), "question")
    _seed(db_path, "q3-reply", "alice", date(2026, 6, 8), "chatter", thread_root_id="q3")
    result = unanswered_all_week_questions(CHANNEL_ID, WEEK_END, _config(), db_path=db_path)
    assert [f.message_id for f in result] == ["q3"]


# --- gather_weekly_facts ---------------------------------------------------


def test_gather_weekly_facts_reports_excluded_members_with_their_reason(db_path):
    config = _config(exceptions=[{"member_id": "bob", "reason": "On leave"}])
    facts = gather_weekly_facts(CHANNEL_ID, WEEK_END, config, db_path=db_path)
    assert facts.excluded_members[0].member_id == "bob"
    assert facts.excluded_members[0].reason == "On leave"
    assert "bob" not in facts.participation
    assert facts.week_start == "2026-05-30"
    assert facts.week_end == "2026-06-05"
