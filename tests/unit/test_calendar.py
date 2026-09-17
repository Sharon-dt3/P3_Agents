from datetime import date, time

from p1.adapters.teams_reader import TeamsMessage
from p1.config.calendar import is_working_day, local_datetime, parse_instant, to_local
from p1.config.schema import ChannelConfig

TZ = "Asia/Colombo"


def make_config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "19:proj-test@thread.tacv2",
        "display_name": "Project Test",
        "allowlisted": True,
        "roster": ["alice"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": TZ,
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "daily_digest_time": time(11, 30),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def test_parse_instant_handles_trailing_z():
    parsed = parse_instant("2025-06-02T09:30:00Z")
    assert parsed.utcoffset().total_seconds() == 0


def test_to_local_converts_across_timezones():
    # 09:30 America/New_York is 13:30 UTC.
    local = to_local("2025-06-02T13:30:00Z", "America/New_York")
    assert local.hour == 9
    assert local.minute == 30


def test_local_datetime_uses_the_messages_posted_at():
    message = TeamsMessage(
        id="m1", channel_id="19:proj-test@thread.tacv2", author_id="alice",
        posted_at="2025-06-02T09:30:00+05:30", body="hi",
    )
    local = local_datetime(message, make_config())
    assert local.date() == date(2025, 6, 2)
    assert local.time() == time(9, 30)


def test_is_working_day_true_for_an_ordinary_weekday():
    assert is_working_day(date(2025, 6, 2), make_config()) is True  # a Monday


def test_is_working_day_false_for_a_weekend():
    assert is_working_day(date(2025, 6, 7), make_config()) is False  # a Saturday


def test_is_working_day_false_for_a_configured_non_working_date():
    config = make_config(non_working_dates=[date(2025, 6, 13)])
    assert is_working_day(date(2025, 6, 13), config) is False  # a Friday, otherwise a working day
