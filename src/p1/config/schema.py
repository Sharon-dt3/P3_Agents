"""
Channel registry and per-channel configuration (CHN-02).

The roster and window ARE the product -- every non-responder claim is
only as defensible as the config behind it. This is validated, never
a bag of literals scattered through the codebase.
"""

from __future__ import annotations

from datetime import time

from pydantic import BaseModel, Field, field_validator

WORKING_DAY_NAMES = {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}


class ExceptionEntry(BaseModel):
    member_id: str
    reason: str


class ChannelConfig(BaseModel):
    channel_id: str
    display_name: str
    allowlisted: bool = True

    roster: list[str] = Field(min_length=1)
    update_window_start: time
    update_window_end: time
    timezone: str
    working_days: list[str] = Field(min_length=1)

    length_floor: int = 10
    count_thread_replies: bool = True
    ignore_bots: bool = True

    daily_digest_time: time
    weekly_digest_day: str
    weekly_digest_time: time

    nudge_enabled: bool = False
    nudge_cap_per_day: int = 1
    escalation_threshold_days: int = 3
    channel_owner_id: str
    exceptions: list[ExceptionEntry] = Field(default_factory=list)

    version: int = 1

    @field_validator("working_days")
    @classmethod
    def _validate_working_days(cls, v):
        invalid = set(v) - WORKING_DAY_NAMES
        if invalid:
            raise ValueError(f"Unknown working day(s): {sorted(invalid)}")
        return v

    @field_validator("weekly_digest_day")
    @classmethod
    def _validate_weekly_day(cls, v):
        if v not in WORKING_DAY_NAMES:
            raise ValueError(f"Unknown day: {v}")
        return v

    @field_validator("update_window_end")
    @classmethod
    def _validate_window_order(cls, v, info):
        start = info.data.get("update_window_start")
        if start is not None and v <= start:
            raise ValueError("update_window_end must be after update_window_start")
        return v
