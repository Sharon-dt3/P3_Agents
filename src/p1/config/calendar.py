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

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Matches the fractional-seconds group in an ISO 8601 timestamp, e.g.
# the ".35" in "2026-09-16T10:49:31.35+00:00".
_FRACTIONAL_SECONDS_RE = re.compile(r"\.(\d+)")


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, tolerating two real shapes
    datetime.fromisoformat on Python 3.10 rejects outright:

    - a trailing 'Z' (UTC), which 3.10's fromisoformat does not accept
      directly (relaxed in 3.11+, but this repo runs on 3.10);
    - a fractional-seconds component whose length isn't exactly 3 or 6
      digits. 3.10's fromisoformat is stricter than ISO 8601 itself
      requires here -- and both shapes it rejects are real, not
      hypothetical: Microsoft Graph's own dateTimeOffset format uses 7
      digits (.NET's 100ns ticks, e.g. "2019-07-12T15:00:00.0000000Z"),
      while at least one message already ingested into this system's
      own live database carries a 2-digit fraction ("...31.35Z") --
      whatever produced that value, Python must still be able to parse
      it. Any digit count is normalized to 6 (microseconds), padding a
      short fraction with trailing zeros and truncating a long one --
      datetime itself only stores microsecond precision, so truncating
      Graph's sub-microsecond tick digits loses nothing Python could
      have kept anyway. See DECISION_LOG.md for the crash this fixes.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    match = _FRACTIONAL_SECONDS_RE.search(value)
    if match:
        normalized = (match.group(1) + "000000")[:6]
        value = value[: match.start()] + "." + normalized + value[match.end() :]

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
