"""
Weekly roll-up fact-gathering (CHN-19) -- the same "facts in code,
prose from the model" split CHN-13 already drew (see p1.reporting.facts),
at weekly granularity. Every quantitative claim in the weekly roll-up --
a participation rate, a week-over-week trend, which blockers recurred,
which decisions were taken, which questions went unanswered -- is
computed here by ordinary arithmetic against the classifications and
messages tables directly, never estimated or summarized by a model.
This module has no import of p1.llm or p1.prompts anywhere in it, for
the same reason facts.py doesn't (SPN-05's test_no_inline_prompts.py).

A week is a fixed 7-calendar-day window ending on `week_end` (inclusive)
-- the day a channel's weekly digest actually fires
(config.weekly_digest_day), though every function here takes week_end
as a plain argument and never reads a clock itself, the same
clock-override posture CHN-17's is_due()/run_daily_digest_job(day=...)
already established. "Working days" within that window are exactly the
days is_working_day() says yes to -- config.working_days minus
config.non_working_dates -- so a channel configured Mon-Fri never has a
weekend day counted against anyone's participation rate, and a
configured holiday inside the window is excluded from the denominator
the same way it already is for CHN-10's daily ledger.

Participation rate per roster member = (working days this week the
member has at least one non-deleted, roster-authored message classified
update/blocker/decision/question) / (working days this week) -- the
identical CONTRIBUTOR_LABELS set CHN-10's ledger already uses, so a
member who only posted chatter this week is exactly as "did not
contribute" here as CHN-14's "posted, but no update" wording already
treats them daily. A member on config.exceptions is excluded from the
participation dict entirely (reported separately, with their reason),
not given a rate of zero -- an on-leave week is not a bad week.

Trend is simply this week's rate minus the immediately prior week's
rate (both computed by the identical arithmetic above, scoped to their
own 7-day window) -- never a model's impression of "improving" or
"declining."

A blocker is "recurring" this week if the same roster author raised at
least one blocker-labeled message on two or more DISTINCT local days
within the week -- a deliberately mechanical, code-checkable definition
(no topic clustering, no model judgement of whether two blockers are
"the same issue") that still catches the case a weekly roll-up actually
cares about: someone raising the same kind of problem more than once
rather than a single bad day.

Questions "that went unanswered all week" means exactly that: no
non-deleted thread reply exists with its own local posted_at on or
before week_end -- a reply that arrives the following week does not
retroactively make this week's question answered. This is a narrower
question than CHN-13's own "still awaiting an answer as of right now"
(which only asks about the present moment); the two are deliberately
different checks for deliberately different reports. See
DECISION_LOG.md.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path

from p1.config.calendar import is_working_day, to_local
from p1.config.schema import ChannelConfig
from p1.storage.db import DEFAULT_DB_PATH, get_connection

# The same four labels CHN-10's participation ledger already treats as
# "this member contributed something today" -- update/blocker/decision/
# question all count; chatter and noise never do.
CONTRIBUTOR_LABELS = frozenset({"update", "blocker", "decision", "question"})

_SELECT_ROSTER_LABELED_MESSAGES_SQL = (
    "SELECT m.id AS message_id, m.author_id, m.posted_at, m.body_raw, "
    "m.permalink, c.label "
    "FROM messages m JOIN classifications c ON c.message_id = m.id "
    "WHERE m.channel_id = :channel_id AND m.is_deleted = 0 "
    "ORDER BY m.posted_at"
)


def week_bounds(week_end: date_type) -> tuple[date_type, date_type]:
    """The 7-calendar-day window ending on (and including) week_end."""
    return week_end - timedelta(days=6), week_end


def working_days_in_range(start: date_type, end: date_type, config: ChannelConfig) -> list[date_type]:
    days = []
    current = start
    while current <= end:
        if is_working_day(current, config):
            days.append(current)
        current += timedelta(days=1)
    return days


@dataclass(frozen=True)
class MemberWeekParticipation:
    member_id: str
    working_days: int
    contributed_days: int
    rate: float | None  # None only when working_days == 0 for this week


@dataclass(frozen=True)
class ParticipationTrend:
    member_id: str
    current: MemberWeekParticipation
    prior: MemberWeekParticipation
    delta: float | None  # current.rate - prior.rate; None if either rate is None


@dataclass(frozen=True)
class RecurringBlocker:
    author_id: str
    message_ids: tuple[str, ...]  # chronological order
    days: tuple[str, ...]  # distinct ISO dates, sorted, len >= 2


@dataclass(frozen=True)
class WeeklyFact:
    message_id: str
    author_id: str
    body_raw: str
    permalink: str
    label: str
    date: str  # ISO date, this message's own local day


@dataclass(frozen=True)
class ExcludedMember:
    member_id: str
    reason: str


@dataclass(frozen=True)
class WeeklyFacts:
    channel_id: str
    week_start: str
    week_end: str
    participation: dict[str, ParticipationTrend]
    excluded_members: tuple[ExcludedMember, ...]
    recurring_blockers: list[RecurringBlocker]
    decisions: list[WeeklyFact]
    unanswered_questions: list[WeeklyFact]


def _roster_labeled_rows(channel_id: str, config: ChannelConfig, db_path: str | Path) -> list[dict]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(_SELECT_ROSTER_LABELED_MESSAGES_SQL, {"channel_id": channel_id}).fetchall()
    finally:
        conn.close()

    roster = set(config.roster)
    out = []
    for row in rows:
        if row["author_id"] not in roster:
            continue
        local_date = to_local(row["posted_at"], config.timezone).date()
        out.append(
            {
                "message_id": row["message_id"],
                "author_id": row["author_id"],
                "posted_at": row["posted_at"],
                "body_raw": row["body_raw"],
                "permalink": row["permalink"],
                "label": row["label"],
                "date": local_date,
            }
        )
    return out


def member_participation(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, MemberWeekParticipation]:
    """One MemberWeekParticipation per roster member NOT on
    config.exceptions, for the 7-day window ending on week_end."""
    week_start, week_end = week_bounds(week_end)
    working_days = working_days_in_range(week_start, week_end, config)
    working_days_set = set(working_days)
    excepted = {e.member_id for e in config.exceptions}

    rows = _roster_labeled_rows(channel_id, config, db_path)
    contributed_by_member: dict[str, set] = {m: set() for m in config.roster if m not in excepted}
    for row in rows:
        if (
            row["author_id"] in contributed_by_member
            and row["label"] in CONTRIBUTOR_LABELS
            and week_start <= row["date"] <= week_end
        ):
            contributed_by_member[row["author_id"]].add(row["date"])

    result: dict[str, MemberWeekParticipation] = {}
    for member_id, days_contributed in contributed_by_member.items():
        contributed_working_days = len(days_contributed & working_days_set)
        result[member_id] = MemberWeekParticipation(
            member_id=member_id,
            working_days=len(working_days),
            contributed_days=contributed_working_days,
            rate=(contributed_working_days / len(working_days)) if working_days else None,
        )
    return result


def participation_trend(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, ParticipationTrend]:
    current = member_participation(channel_id, week_end, config, db_path=db_path)
    week_start, _ = week_bounds(week_end)
    prior_week_end = week_start - timedelta(days=1)
    prior = member_participation(channel_id, prior_week_end, config, db_path=db_path)

    out: dict[str, ParticipationTrend] = {}
    for member_id, current_week in current.items():
        prior_week = prior.get(
            member_id,
            MemberWeekParticipation(member_id=member_id, working_days=0, contributed_days=0, rate=None),
        )
        delta = None
        if current_week.rate is not None and prior_week.rate is not None:
            delta = current_week.rate - prior_week.rate
        out[member_id] = ParticipationTrend(
            member_id=member_id, current=current_week, prior=prior_week, delta=delta,
        )
    return out


def recurring_blockers(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[RecurringBlocker]:
    week_start, week_end = week_bounds(week_end)
    rows = _roster_labeled_rows(channel_id, config, db_path)

    by_author: dict[str, list[dict]] = {}
    for row in rows:
        if row["label"] == "blocker" and row["permalink"] and week_start <= row["date"] <= week_end:
            by_author.setdefault(row["author_id"], []).append(row)

    result = []
    for author_id in sorted(by_author):
        author_rows = sorted(by_author[author_id], key=lambda r: r["posted_at"])
        distinct_days = sorted({r["date"] for r in author_rows})
        if len(distinct_days) >= 2:
            result.append(
                RecurringBlocker(
                    author_id=author_id,
                    message_ids=tuple(r["message_id"] for r in author_rows),
                    days=tuple(d.isoformat() for d in distinct_days),
                )
            )
    return result


def weekly_decisions(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[WeeklyFact]:
    week_start, week_end = week_bounds(week_end)
    rows = _roster_labeled_rows(channel_id, config, db_path)
    facts = [
        WeeklyFact(
            message_id=r["message_id"], author_id=r["author_id"], body_raw=r["body_raw"],
            permalink=r["permalink"], label=r["label"], date=r["date"].isoformat(),
        )
        for r in rows
        if r["label"] == "decision" and r["permalink"] and week_start <= r["date"] <= week_end
    ]
    return sorted(facts, key=lambda f: (f.date, f.message_id))


def unanswered_all_week_questions(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> list[WeeklyFact]:
    week_start, week_end = week_bounds(week_end)
    rows = _roster_labeled_rows(channel_id, config, db_path)
    question_rows = [
        r for r in rows
        if r["label"] == "question" and r["permalink"] and week_start <= r["date"] <= week_end
    ]
    if not question_rows:
        return []

    question_ids = [r["message_id"] for r in question_rows]
    conn = get_connection(db_path)
    try:
        placeholders = ", ".join("?" for _ in question_ids)
        reply_rows = conn.execute(
            f"SELECT thread_root_id, posted_at FROM messages "
            f"WHERE thread_root_id IN ({placeholders}) AND is_deleted = 0",
            question_ids,
        ).fetchall()
    finally:
        conn.close()

    # A reply answers its question for THIS week's purposes only if it
    # was itself posted on or before week_end -- a reply that arrives
    # the following week does not retroactively make this week's
    # question answered (see module docstring).
    answered_within_week: set[str] = {
        row["thread_root_id"]
        for row in reply_rows
        if to_local(row["posted_at"], config.timezone).date() <= week_end
    }

    facts = [
        WeeklyFact(
            message_id=r["message_id"], author_id=r["author_id"], body_raw=r["body_raw"],
            permalink=r["permalink"], label=r["label"], date=r["date"].isoformat(),
        )
        for r in question_rows
        if r["message_id"] not in answered_within_week
    ]
    return sorted(facts, key=lambda f: (f.date, f.message_id))


def gather_weekly_facts(
    channel_id: str,
    week_end: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> WeeklyFacts:
    week_start, week_end_resolved = week_bounds(week_end)
    roster = set(config.roster)
    excluded_members = tuple(
        sorted(
            (ExcludedMember(member_id=e.member_id, reason=e.reason) for e in config.exceptions if e.member_id in roster),
            key=lambda e: e.member_id,
        )
    )
    return WeeklyFacts(
        channel_id=channel_id,
        week_start=week_start.isoformat(),
        week_end=week_end_resolved.isoformat(),
        participation=participation_trend(channel_id, week_end, config, db_path=db_path),
        excluded_members=excluded_members,
        recurring_blockers=recurring_blockers(channel_id, week_end, config, db_path=db_path),
        decisions=weekly_decisions(channel_id, week_end, config, db_path=db_path),
        unanswered_questions=unanswered_all_week_questions(channel_id, week_end, config, db_path=db_path),
    )
