"""
Shared calendar/timezone arithmetic (originally part of detection/rules.py,
CHN-08). Factored out here once CHN-10's participation ledger needed the
exact same "is this a working day" and "what is this message's local
time" logic that CHN-08's rules already computed. Two independent
copies of either could silently drift apart over time -- one honouring
non_working_dates and the other not, say -- and CHN-08 and CHN-10
disagreeing about which days count would be a real correctness bug, not
a style complaint. One shared place means they can't disagree.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, tolerating a trailing 'Z' (UTC) the
    way datetime.fromisoformat on Python 3.10 does not."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def to_local(instant: str, timezone: str) -> datetime:
    """An ISO 8601 instant, converted into the given IANA timezone."""
    return parse_instant(instant).astimezone(ZoneInfo(timezone))


def local_datetime(message: TeamsMessage, config: ChannelConfig) -> datetime:
    """The message's ORIGINAL post time (never edited_at), converted
    into the channel's own configured timezone -- callers must always
    reason about a message's day/time here, never in whatever offset the
    timestamp happened to arrive in."""
    return to_local(message.posted_at, config.timezone)


def is_working_day(day: date, config: ChannelConfig) -> bool:
    if day in config.non_working_dates:
        return False
    return WEEKDAY_NAMES[day.weekday()] in config.working_days
