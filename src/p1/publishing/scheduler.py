"""
CHN-17: the clock, split from the job (P1 Channel) -- now a thin
P1-facing wrapper over the generalized spine.scheduling engine (CHN-33
extraction).

"A button labelled 'run the digest' is a test harness, not a
scheduler." -- this row's own rationale, unchanged. The real decision
logic (is_due()'s pure comparison, build_scheduler()'s CronTrigger
wiring) now lives in spine.scheduling.scheduler, generalized to take a
ScheduleSpec instead of a concrete ChannelConfig. This module's own
public API -- is_due(config, moment), build_scheduler(configs, gateway,
publisher, *, db_path=...) -- is byte-for-byte unchanged from before
CHN-33, so every existing call site (live_runner_*.py,
publishing/daily_job.py) and this module's own test suite
(tests/unit/test_scheduler.py) needs no changes.

_to_spec() below is the only P1-specific glue this module still owns:
turning a ChannelConfig into the five plain fields
spine.scheduling.scheduler.ScheduleSpec needs, and building
run_daily_digest_job's own kwargs -- exactly the two things spine's
build_scheduler() asks any caller to supply for itself. See
DECISION_LOG.md, 2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from spine.scheduling.scheduler import ScheduleSpec
from spine.scheduling.scheduler import build_scheduler as _spine_build_scheduler
from spine.scheduling.scheduler import is_due as _spine_is_due

from p1.config.schema import ChannelConfig
from p1.publishing.daily_job import run_daily_digest_job
from p1.storage.db import DEFAULT_DB_PATH

__all__ = ["is_due", "build_scheduler"]


def _to_spec(config: ChannelConfig) -> ScheduleSpec:
    return ScheduleSpec(
        job_id=f"daily_digest:{config.channel_id}",
        timezone=config.timezone,
        working_days=config.working_days,
        non_working_dates=config.non_working_dates,
        scheduled_time=config.daily_digest_time,
    )


def is_due(config: ChannelConfig, moment: datetime) -> bool:
    """True iff `moment`, expressed in this channel's own local time, is
    exactly this channel's configured daily_digest_time on one of its
    configured working days (and not a non_working_date). Delegates to
    spine.scheduling.scheduler.is_due(); unchanged behaviour from before
    CHN-33."""
    return _spine_is_due(_to_spec(config), moment)


def build_scheduler(
    configs: list[ChannelConfig],
    gateway,
    publisher,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> BackgroundScheduler:
    """The real production scheduler: one CronTrigger per channel, firing
    at that channel's own local daily_digest_time on its own working
    days, in its own timezone. Thin P1-specific wrapper over
    spine.scheduling.scheduler.build_scheduler(): this function supplies
    the ChannelConfig -> ScheduleSpec translation and
    run_daily_digest_job's own kwargs; the CronTrigger wiring itself is
    spine's, unchanged from before CHN-33. Callers add further jobs and
    start() the returned scheduler; nothing here starts it."""
    return _spine_build_scheduler(
        configs,
        to_spec=_to_spec,
        job_fn=run_daily_digest_job,
        job_kwargs=lambda config: {
            "channel_id": config.channel_id,
            "config": config,
            "gateway": gateway,
            "publisher": publisher,
            "db_path": db_path,
        },
    )
