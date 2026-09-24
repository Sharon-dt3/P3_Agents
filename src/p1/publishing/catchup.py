"""
Same-day catch-up for scheduled publishing.

A cron-style scheduler only fires at the scheduled minute (plus a grace
window while the process is alive); it never looks backward. So a digest
missed because the laptop lost its internet at 17:30, or the runner was
down, or every send retry failed, stayed missed -- found 2026-09-24, when
a ~3 hour outage beat a 4-minute retry window and the digest went out at
20:57, hours late and with stale content.

overdue_daily() / overdue_weekly() answer one question: "is this
channel's daily digest (or weekly roll-up) due by now, today, in its own
timezone, and still not sent?" run_missed_publishing() acts on it. A live
runner calls it on a timer, so recovery does not depend on remembering to
restart or re-run anything -- it heals as soon as the network is back.

Deliberately conservative:
  - TODAY only (the channel's local date). Restarting on Monday morning
    never posts Friday's digest.
  - Only after a grace window past the scheduled minute, so it never races
    the scheduled job itself.
  - Skips anything waiting for a human (a pending proposal -- including the
    first-ever weekly roll-up), anything a human rejected, and anything
    already sent. It only retries what is genuinely approved-or-unstarted
    and unsent, so it cannot spam an approval queue or override a decision.
Both jobs it calls are idempotent (a rerun can never post twice).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from p1.approval.proposals import APPLIED, PENDING, REJECTED, ProposalStore
from p1.config.calendar import is_working_day
from p1.config.schema import ChannelConfig
from p1.publishing.daily_job import run_daily_digest_job
from p1.publishing.weekly_job import run_weekly_rollup_job
from p1.storage.db import DEFAULT_DB_PATH
from p1.storage.digests_repo import DigestStore

DEFAULT_GRACE_MINUTES = 10
_WEEKDAY = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_NOT_RETRIED = (PENDING, REJECTED, APPLIED)


def _local_now(config: ChannelConfig, now: datetime | None) -> datetime:
    zone = ZoneInfo(config.timezone)
    return (now or datetime.now(zone)).astimezone(zone)


def _unsent(digest_store: DigestStore, proposal_store: ProposalStore, cid: str, day: str, kind: str) -> bool:
    row = digest_store.get_by_idempotency_key(f"{cid}:{day}:{kind}")
    if row and row["published_at"]:
        return False
    proposal = proposal_store.get_by_idempotency_key(f"{cid}:{day}:{kind}_publish")
    return proposal is None or proposal.status not in _NOT_RETRIED


def overdue_daily(
    config: ChannelConfig, now: datetime | None = None, *, db_path: str | Path = DEFAULT_DB_PATH,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> bool:
    local = _local_now(config, now)
    today = local.date()
    if not is_working_day(today, config):
        return False
    due = datetime.combine(today, config.daily_digest_time, tzinfo=local.tzinfo) + timedelta(minutes=grace_minutes)
    if local < due:
        return False
    return _unsent(DigestStore(db_path), ProposalStore(db_path), config.channel_id, today.isoformat(), "daily")


def overdue_weekly(
    config: ChannelConfig, now: datetime | None = None, *, db_path: str | Path = DEFAULT_DB_PATH,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> bool:
    local = _local_now(config, now)
    today = local.date()
    if _WEEKDAY[local.weekday()] != config.weekly_digest_day or today in config.non_working_dates:
        return False
    due = datetime.combine(today, config.weekly_digest_time, tzinfo=local.tzinfo) + timedelta(minutes=grace_minutes)
    if local < due:
        return False
    return _unsent(DigestStore(db_path), ProposalStore(db_path), config.channel_id, today.isoformat(), "weekly")


def run_missed_publishing(
    config: ChannelConfig,
    gateway,
    publisher,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    now: datetime | None = None,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
    daily_job=run_daily_digest_job,
    weekly_job=run_weekly_rollup_job,
    before=None,
) -> list[tuple[str, object]]:
    """Runs whichever of today's daily digest / weekly roll-up is overdue and
    unsent. Returns [(kind, JobResult), ...] for what it ran (empty when
    nothing was overdue). A job that raises propagates: the caller logs it
    and simply tries again on the next tick."""
    ran: list[tuple[str, object]] = []
    kwargs = {"channel_id": config.channel_id, "config": config, "gateway": gateway,
              "publisher": publisher, "db_path": db_path}
    daily_due = overdue_daily(config, now, db_path=db_path, grace_minutes=grace_minutes)
    weekly_due = overdue_weekly(config, now, db_path=db_path, grace_minutes=grace_minutes)
    if (daily_due or weekly_due) and before is not None:
        # `before` pulls fresh data (see the live runners). If it raises, nothing is
        # published this tick and the caller retries on the next one.
        before()
    if daily_due:
        ran.append(("digest", daily_job(**kwargs)))
    if weekly_due:
        ran.append(("weekly", weekly_job(**kwargs)))
    return ran
