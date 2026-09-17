"""
CHN-17: is_due() is the pure, clock-injectable half of scheduling;
build_scheduler() is the thin real-APScheduler wiring around it. These
tests exercise is_due() directly (the actual "clock override for
demos" mechanism -- see scheduler.py's own docstring) and introspect
build_scheduler()'s CronTrigger fields rather than waiting on a real
background thread to fire, which would make this suite slow and
timing-flaky for no extra coverage: build_scheduler() only ever
translates a ChannelConfig into trigger fields, and that translation is
what's worth testing here, not APScheduler's own clock.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from p1.config.schema import ChannelConfig
from p1.publishing.scheduler import build_scheduler, is_due


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "sched-channel",
        "display_name": "Scheduler Test Channel",
        "roster": ["alice"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": "Asia/Tokyo",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "non_working_dates": [],
        "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


# --- is_due --------------------------------------------------------------


def test_is_due_true_at_the_exact_local_minute_on_a_working_day():
    config = _config(timezone="Asia/Tokyo", daily_digest_time=time(9, 0))
    # 2026-06-01 is a Monday. 00:00 UTC == 09:00 JST (UTC+9).
    moment = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    assert is_due(config, moment) is True


def test_is_due_false_a_minute_either_side_of_the_exact_time():
    config = _config(timezone="Asia/Tokyo", daily_digest_time=time(9, 0))
    before = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc).astimezone(ZoneInfo("Asia/Tokyo"))
    assert is_due(config, before.replace(minute=59, hour=8)) is False
    assert is_due(config, before.replace(minute=1, hour=9)) is False


def test_is_due_false_on_a_non_working_day_even_at_the_exact_time():
    config = _config(
        timezone="Asia/Tokyo", daily_digest_time=time(9, 0), working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
    )
    # 2026-06-06 is a Saturday.
    moment = datetime(2026, 6, 5, 15, 0, tzinfo=timezone.utc)  # 2026-06-06 00:00 JST
    assert is_due(config, moment) is False


def test_is_due_false_on_an_explicit_non_working_date():
    config = _config(
        timezone="Asia/Tokyo", daily_digest_time=time(9, 0), non_working_dates=[date(2026, 6, 1)],
    )
    moment = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    assert is_due(config, moment) is False


def test_is_due_converts_to_each_channels_own_timezone_independently():
    """The same absolute instant is due for a channel whose local time
    it matches and not due for one whose local time it doesn't --
    is_due() never compares against a shared reference time, only each
    config's own timezone."""
    tokyo = _config(channel_id="tokyo", timezone="Asia/Tokyo", daily_digest_time=time(9, 0))
    london = _config(channel_id="london", timezone="Europe/London", daily_digest_time=time(9, 0))
    moment = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)  # 09:00 JST, 01:00 BST
    assert is_due(tokyo, moment) is True
    assert is_due(london, moment) is False


# --- build_scheduler -------------------------------------------------------


def _field(trigger: CronTrigger, name: str) -> str:
    return next(str(f) for f in trigger.fields if f.name == name)


def test_build_scheduler_wires_one_job_per_channel():
    configs = [
        _config(channel_id="c1", timezone="Asia/Tokyo", daily_digest_time=time(9, 0)),
        _config(channel_id="c2", timezone="Europe/London", daily_digest_time=time(8, 30)),
        _config(channel_id="c3", timezone="America/New_York", daily_digest_time=time(7, 15)),
    ]
    scheduler = build_scheduler(configs, gateway=object(), publisher=object())
    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert set(jobs) == {"daily_digest:c1", "daily_digest:c2", "daily_digest:c3"}


def test_build_scheduler_trigger_matches_each_channels_own_config():
    configs = [
        _config(
            channel_id="c1", timezone="Asia/Tokyo", daily_digest_time=time(9, 0),
            working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        ),
        _config(
            channel_id="c2", timezone="Europe/London", daily_digest_time=time(8, 30),
            working_days=["Mon", "Wed", "Fri"],
        ),
    ]
    scheduler = build_scheduler(configs, gateway=object(), publisher=object())
    jobs = {job.id: job for job in scheduler.get_jobs()}

    trigger_c1 = jobs["daily_digest:c1"].trigger
    assert str(trigger_c1.timezone) == "Asia/Tokyo"
    assert _field(trigger_c1, "hour") == "9"
    assert _field(trigger_c1, "minute") == "0"
    assert _field(trigger_c1, "day_of_week") == "mon,tue,wed,thu,fri"

    trigger_c2 = jobs["daily_digest:c2"].trigger
    assert str(trigger_c2.timezone) == "Europe/London"
    assert _field(trigger_c2, "hour") == "8"
    assert _field(trigger_c2, "minute") == "30"
    assert _field(trigger_c2, "day_of_week") == "mon,wed,fri"


def test_build_scheduler_never_starts_the_scheduler():
    """Constructing the scheduler must not start a background thread --
    tests (and a demo inspecting the wiring) must be able to build one
    without a real clock ever firing a job."""
    scheduler = build_scheduler(
        [_config(channel_id="c1")], gateway=object(), publisher=object(),
    )
    assert scheduler.running is False
