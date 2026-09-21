"""
Thin re-export shim -- CHN-33: real implementation now lives in
spine.config.calendar, moved there and generalized. is_working_day()/
local_datetime() now take structural Protocols (WorkingCalendarConfig/
TimestampedItem/TimezonedConfig) instead of the concrete
p1.config.schema.ChannelConfig/p1.adapters.teams_reader.TeamsMessage --
P1's own types already have the exact field names those Protocols
require (working_days, non_working_dates, timezone, posted_at), so this
is a pure widening of the accepted type, not a behaviour change; Python
does not enforce these hints at runtime regardless. See
spine/config/calendar.py's own docstring and DECISION_LOG.md, 2026-09-21
CHN-33 entry.
"""

from __future__ import annotations

from spine.config.calendar import (
    WEEKDAY_NAMES,
    is_working_day,
    local_datetime,
    parse_instant,
    to_local,
)

__all__ = ["WEEKDAY_NAMES", "is_working_day", "local_datetime", "parse_instant", "to_local"]
