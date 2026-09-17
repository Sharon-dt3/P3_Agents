"""
CHN-17: the clock, split from the job (P1 Channel).

"A button labelled 'run the digest' is a test harness, not a
scheduler." -- this row's own rationale. This module is the only place
in the codebase that knows what time it really is. Everything it
decides -- is a given channel due right now -- is expressed as one pure
function, is_due(config, moment), that takes the moment as an ordinary
argument rather than reading a clock itself. That is the entire "clock
override for demos" mechanism: a demo calls is_due(config, moment) (or
daily_job.run_daily_digest_job(..., day=...)) with whatever moment or
day it wants to pretend it is, and gets exactly the same decision
production would make at that real moment -- no fake clock, no
monkeypatched datetime, no APScheduler internals to fight. See
DECISION_LOG.md for why this two-layer split (a pure decision function
plus a thin real-scheduler wrapper) was chosen over trying to inject a
fake clock into APScheduler itself.

build_scheduler() is the actual production wiring: one real APScheduler
CronTrigger per channel, firing at that channel's own configured local
time, on its own configured working days, in its own configured
timezone -- APScheduler (not this module) is what tracks wall-clock
time in production. Nothing about is_due() is re-implemented inside a
CronTrigger's own fields; build_scheduler() only translates a
ChannelConfig into the CronTrigger fields that make APScheduler fire at
the same moments is_due() would say yes to, so a demo exercising
is_due()/run_daily_digest_job() directly is exercising the same rule
production's real scheduler enforces, not a parallel copy of it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from p1.config.calendar import is_working_day
from p1.config.schema import ChannelConfig
from p1.publishing.daily_job import run_daily_digest_job
from p1.storage.db import DEFAULT_DB_PATH

# ChannelConfig.working_days uses these three-letter names; CronTrigger's
# day_of_week wants APScheduler's own abbreviations, which happen to be
# the same three letters lower-cased -- but spelled out explicitly here
# rather than relying on that coincidence continuing to hold.
_CRON_DAY_NAMES = {
    "Mon": "mon", "Tue": "tue", "Wed": "wed", "Thu": "thu",
    "Fri": "fri", "Sat": "sat", "Sun": "sun",
}


def is_due(config: ChannelConfig, moment: datetime) -> bool:
    """True iff `moment`, expressed in this channel's own local time, is
    exactly this channel's configured daily_digest_time on one of its
    configured working days (and not a non_working_date). Minute
    resolution, not second/microsecond -- a scheduler firing once a
    minute (real APScheduler, or a demo stepping through a day
    minute-by-minute) will see exactly one due minute per channel per
    day, never zero and never more than one, since daily_digest_time is
    a single hour:minute pair.

    `moment` may be any timezone-aware datetime (UTC in production, or
    whatever a demo chooses) -- it is converted to config.timezone
    before anything is compared, since "channel-local time" is the only
    time this function knows about.
    """
    local = moment.astimezone(ZoneInfo(config.timezone))
    if not is_working_day(local.date(), config):
        return False
    target = config.daily_digest_time
    return local.hour == target.hour and local.minute == target.minute


def build_scheduler(
    configs: list[ChannelConfig],
    gateway,
    publisher,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> BackgroundScheduler:
    """The real production scheduler: one CronTrigger per channel,
    firing at that channel's own local daily_digest_time on its own
    working days, in its own timezone -- so three channels in three
    timezones each fire at their own correct wall-clock moment without
    this process ever converting anything to a shared reference time
    itself. Callers add jobs and start() the returned scheduler; nothing
    here starts it, so tests can inspect the wiring without ever
    running a real background thread."""
    scheduler = BackgroundScheduler()
    for config in configs:
        day_of_week = ",".join(
            _CRON_DAY_NAMES[day] for day in config.working_days if day in _CRON_DAY_NAMES
        )
        trigger = CronTrigger(
            day_of_week=day_of_week,
            hour=config.daily_digest_time.hour,
            minute=config.daily_digest_time.minute,
            timezone=ZoneInfo(config.timezone),
        )
        scheduler.add_job(
            run_daily_digest_job,
            trigger=trigger,
            id=f"daily_digest:{config.channel_id}",
            kwargs={
                "channel_id": config.channel_id,
                "config": config,
                "gateway": gateway,
                "publisher": publisher,
                "db_path": db_path,
            },
        )
    return scheduler
