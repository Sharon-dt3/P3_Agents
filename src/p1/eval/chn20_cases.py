"""
Golden case 11 (CHN-20): weekly arithmetic reproducibility.

"Automated check that every number in the weekly roll-up can be
recomputed from the stored messages, including the week containing a
non-working day."

This is deliberately NOT a unit test that hand-picks literal expected
numbers (test_weekly_facts.py / test_weekly_summary.py already do that,
row by row). Instead it takes the same posture GC9 already takes toward
CHN-16's dual-generation grounding check: define one seed data set as
plain data, feed it through TWO independent computations, and assert
they agree on every figure.

  1. The production path -- the seed messages are inserted into a real
     sqlite db exactly as ingestion would, and
     p1.reporting.weekly_facts.gather_weekly_facts() is called against
     it, exactly as generate_weekly_rollup() calls it in production.

  2. A from-scratch recomputation -- _independent_recompute() below
     re-derives every participation rate, trend delta, recurring
     blocker, decision and unanswered question directly from the same
     literal seed list, using its own small re-implementation of
     "is this a working day," "did this member contribute today," and
     the three window-scoped fact queries. It does not import, call, or
     otherwise depend on any function in p1.reporting.weekly_facts --
     only the module's own frozen dataclasses are reused as plain
     result shapes, never its logic.

If the two computations ever disagree, GC11-arithmetic-mismatch-count
catches it. The scenario is built so a genuine bug has somewhere to
hide: the current week has a company holiday (a declared
non_working_dates entry) sitting between two working days, and one
roster member raises the SAME blocker again on that exact holiday. That
message must still count toward "recurring blocker" (which scopes to
the calendar week window, not to working days -- see weekly_facts.py's
own module docstring) while NOT counting toward that member's
participation rate (which scopes strictly to working days) --
GC11-non-working-day-scenario-check confirms the scenario actually
exercises that split, so a version of this case that accidentally
dropped the holiday, or moved it outside the week, would fail loudly
rather than silently checking nothing.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, time, timedelta
from pathlib import Path

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.eval.cases import GoldenCase, GoldenCaseRegistry, MetricResult, equals
from p1.reporting.weekly_facts import (
    ExcludedMember,
    MemberWeekParticipation,
    ParticipationTrend,
    RecurringBlocker,
    WeeklyFact,
    gather_weekly_facts,
)
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

CHANNEL_ID = "gc11-channel"
TZ = "UTC"
WEEK_END = date(2026, 8, 7)  # Friday
NON_WORKING_DATE = date(2026, 8, 5)  # Wednesday, mid-week, declared a holiday
ROSTER = ["nina", "omar"]
CONTRIBUTOR_LABELS = frozenset({"update", "blocker", "decision", "question"})
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass(frozen=True)
class _SeedMessage:
    message_id: str
    author_id: str
    day: date
    label: str
    body: str = "text"
    thread_root_id: str | None = None


def _config() -> ChannelConfig:
    return ChannelConfig(
        channel_id=CHANNEL_ID,
        display_name="GC11 Channel",
        allowlisted=True,
        roster=ROSTER,
        update_window_start=time(9, 0),
        update_window_end=time(11, 0),
        timezone=TZ,
        working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        non_working_dates=[NON_WORKING_DATE],
        daily_digest_time=time(9, 0),
        weekly_digest_day="Fri",
        weekly_digest_time=time(16, 0),
        channel_owner_id="nina",
    )


def _seed_messages() -> list[_SeedMessage]:
    return [
        # -- nina: participation/trend subject, plus the week's one
        # decision and both question scenarios (answered-in-week vs.
        # answered-the-following-week).
        _SeedMessage("p-n1", "nina", date(2026, 7, 27), "update"),
        _SeedMessage("p-n2", "nina", date(2026, 7, 28), "update"),
        _SeedMessage("p-n3", "nina", date(2026, 7, 29), "update"),  # prior week: 3 of 5
        _SeedMessage("c-n1", "nina", date(2026, 8, 3), "update"),
        _SeedMessage("c-n-chat1", "nina", date(2026, 8, 4), "chatter", body="lol"),  # never contributes
        _SeedMessage("c-n2", "nina", date(2026, 8, 6), "update"),
        _SeedMessage(
            "c-n-dec1", "nina", date(2026, 8, 7), "decision",
            body="We decided to move the release to next sprint.",
        ),
        _SeedMessage("c-n-q1", "nina", date(2026, 8, 6), "question", body="Are we good to ship Friday?"),
        _SeedMessage("c-n-q1-reply", "omar", date(2026, 8, 7), "chatter", thread_root_id="c-n-q1"),
        _SeedMessage("c-n-q2", "nina", date(2026, 8, 7), "question", body="Who is covering next week?"),
        _SeedMessage(
            "c-n-q2-reply", "omar", date(2026, 8, 10), "chatter", thread_root_id="c-n-q2",
        ),  # arrives the following week -- must NOT retroactively answer c-n-q2
        # out-of-window control: a decision the week before must never
        # leak into this week's decisions list.
        _SeedMessage("p-n-dec1", "nina", date(2026, 7, 30), "decision", body="Prior week decision, out of window."),
        # -- omar: recurring-blocker subject, including the holiday.
        _SeedMessage("p-o1", "omar", date(2026, 7, 27), "blocker", body="Blocked on VPN access."),  # prior: 1 of 5
        _SeedMessage("c-o1", "omar", date(2026, 8, 4), "blocker", body="Blocked on the deploy pipeline."),
        _SeedMessage(
            "c-o2", "omar", NON_WORKING_DATE, "blocker", body="Still blocked on the deploy pipeline.",
        ),  # raised again ON the declared holiday
        _SeedMessage("c-o3", "omar", date(2026, 8, 7), "blocker", body="Deploy pipeline still down."),
        _SeedMessage("c-o-q1", "omar", NON_WORKING_DATE, "question", body="Is IT aware of the outage?"),
    ]


@contextmanager
def _seeded_db(messages: list[_SeedMessage]):
    tmp_dir = tempfile.mkdtemp(prefix="chn20_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)",
                (CHANNEL_ID, "GC11 Channel"),
            )
            for member_id in {msg.author_id for msg in messages}:
                conn.execute(
                    "INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id)
                )
            conn.commit()
        finally:
            conn.close()

        message_store = MessageStore(db_path)
        classification_store = ClassificationStore(db_path)
        for msg in messages:
            message_store.upsert_messages(
                [
                    TeamsMessage(
                        id=msg.message_id, channel_id=CHANNEL_ID, author_id=msg.author_id,
                        thread_root_id=msg.thread_root_id, posted_at=f"{msg.day.isoformat()}T09:00:00+00:00",
                        body=msg.body,
                        permalink=f"https://teams.microsoft.com/l/message/{CHANNEL_ID}/{msg.message_id}",
                    )
                ]
            )
            classification_store.record(message_id=msg.message_id, label=msg.label, method="model", confidence=0.9)
        yield db_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# --- the independent recomputation -- no import of weekly_facts logic ------


def _week_bounds(week_end: date) -> tuple[date, date]:
    return week_end - timedelta(days=6), week_end


def _is_working_day(day: date, config: ChannelConfig) -> bool:
    if day in set(config.non_working_dates):
        return False
    return WEEKDAY_NAMES[day.weekday()] in config.working_days


def _working_days_in_range(start: date, end: date, config: ChannelConfig) -> list[date]:
    days = []
    current = start
    while current <= end:
        if _is_working_day(current, config):
            days.append(current)
        current += timedelta(days=1)
    return days


def _independent_participation(
    messages: list[_SeedMessage], config: ChannelConfig, week_end: date,
) -> dict[str, MemberWeekParticipation]:
    week_start, week_end = _week_bounds(week_end)
    working_days = _working_days_in_range(week_start, week_end, config)
    working_days_set = set(working_days)
    roster = set(config.roster)
    excepted = {e.member_id for e in config.exceptions}

    contributed: dict[str, set] = {m: set() for m in roster if m not in excepted}
    for msg in messages:
        if (
            msg.author_id in contributed
            and msg.label in CONTRIBUTOR_LABELS
            and week_start <= msg.day <= week_end
        ):
            contributed[msg.author_id].add(msg.day)

    result: dict[str, MemberWeekParticipation] = {}
    for member_id, days in contributed.items():
        contributed_working_days = len(days & working_days_set)
        result[member_id] = MemberWeekParticipation(
            member_id=member_id,
            working_days=len(working_days),
            contributed_days=contributed_working_days,
            rate=(contributed_working_days / len(working_days)) if working_days else None,
        )
    return result


def _independent_trend(
    messages: list[_SeedMessage], config: ChannelConfig, week_end: date,
) -> dict[str, ParticipationTrend]:
    current = _independent_participation(messages, config, week_end)
    week_start, _ = _week_bounds(week_end)
    prior_week_end = week_start - timedelta(days=1)
    prior = _independent_participation(messages, config, prior_week_end)

    out: dict[str, ParticipationTrend] = {}
    for member_id, current_week in current.items():
        prior_week = prior.get(
            member_id,
            MemberWeekParticipation(member_id=member_id, working_days=0, contributed_days=0, rate=None),
        )
        delta = None
        if current_week.rate is not None and prior_week.rate is not None:
            delta = current_week.rate - prior_week.rate
        out[member_id] = ParticipationTrend(member_id=member_id, current=current_week, prior=prior_week, delta=delta)
    return out


def _independent_recurring_blockers(
    messages: list[_SeedMessage], config: ChannelConfig, week_end: date,
) -> list[RecurringBlocker]:
    week_start, week_end = _week_bounds(week_end)
    roster = set(config.roster)
    by_author: dict[str, list[_SeedMessage]] = {}
    for msg in messages:
        if msg.author_id in roster and msg.label == "blocker" and week_start <= msg.day <= week_end:
            by_author.setdefault(msg.author_id, []).append(msg)

    result = []
    for author_id in sorted(by_author):
        author_msgs = sorted(by_author[author_id], key=lambda m: m.day)
        distinct_days = sorted({m.day for m in author_msgs})
        if len(distinct_days) >= 2:
            result.append(
                RecurringBlocker(
                    author_id=author_id,
                    message_ids=tuple(m.message_id for m in author_msgs),
                    days=tuple(d.isoformat() for d in distinct_days),
                )
            )
    return result


def _independent_decisions(
    messages: list[_SeedMessage], config: ChannelConfig, week_end: date,
) -> list[WeeklyFact]:
    week_start, week_end = _week_bounds(week_end)
    roster = set(config.roster)
    facts = [
        WeeklyFact(
            message_id=m.message_id, author_id=m.author_id, body_raw=m.body,
            permalink=f"https://teams.microsoft.com/l/message/{CHANNEL_ID}/{m.message_id}",
            label=m.label, date=m.day.isoformat(),
        )
        for m in messages
        if m.author_id in roster and m.label == "decision" and week_start <= m.day <= week_end
    ]
    return sorted(facts, key=lambda f: (f.date, f.message_id))


def _independent_unanswered_questions(
    messages: list[_SeedMessage], config: ChannelConfig, week_end: date,
) -> list[WeeklyFact]:
    week_start, week_end = _week_bounds(week_end)
    roster = set(config.roster)
    question_msgs = [
        m for m in messages
        if m.author_id in roster and m.label == "question" and week_start <= m.day <= week_end
    ]
    if not question_msgs:
        return []
    question_ids = {m.message_id for m in question_msgs}

    # Replies are looked up against the WHOLE message set, from any
    # author, exactly like the production SQL's unfiltered thread_root_id
    # lookup -- not scoped to the roster.
    answered_within_week = {
        m.thread_root_id
        for m in messages
        if m.thread_root_id in question_ids and m.day <= week_end
    }

    facts = [
        WeeklyFact(
            message_id=m.message_id, author_id=m.author_id, body_raw=m.body,
            permalink=f"https://teams.microsoft.com/l/message/{CHANNEL_ID}/{m.message_id}",
            label=m.label, date=m.day.isoformat(),
        )
        for m in question_msgs
        if m.message_id not in answered_within_week
    ]
    return sorted(facts, key=lambda f: (f.date, f.message_id))


def _independent_recompute(messages: list[_SeedMessage], config: ChannelConfig, week_end: date) -> dict:
    roster = set(config.roster)
    excluded_members = tuple(
        sorted(
            (ExcludedMember(member_id=e.member_id, reason=e.reason) for e in config.exceptions if e.member_id in roster),
            key=lambda e: e.member_id,
        )
    )
    return {
        "participation": _independent_trend(messages, config, week_end),
        "excluded_members": excluded_members,
        "recurring_blockers": _independent_recurring_blockers(messages, config, week_end),
        "decisions": _independent_decisions(messages, config, week_end),
        "unanswered_questions": _independent_unanswered_questions(messages, config, week_end),
    }


def _measure_gc11() -> list[MetricResult]:
    messages = _seed_messages()
    config = _config()

    with _seeded_db(messages) as db_path:
        production = gather_weekly_facts(CHANNEL_ID, WEEK_END, config, db_path=db_path)

    independent = _independent_recompute(messages, config, WEEK_END)

    mismatches: list[str] = []
    if production.participation != independent["participation"]:
        mismatches.append("participation")
    if production.excluded_members != independent["excluded_members"]:
        mismatches.append("excluded_members")
    if production.recurring_blockers != independent["recurring_blockers"]:
        mismatches.append("recurring_blockers")
    if production.decisions != independent["decisions"]:
        mismatches.append("decisions")
    if production.unanswered_questions != independent["unanswered_questions"]:
        mismatches.append("unanswered_questions")

    omar_trend = production.participation["omar"]
    week_start, week_end_resolved = _week_bounds(WEEK_END)
    current_working_days = set(_working_days_in_range(week_start, week_end_resolved, config))
    holiday_message_is_in_a_recurring_blocker = any(
        NON_WORKING_DATE.isoformat() in blocker.days for blocker in production.recurring_blockers
    )
    holiday_excluded_from_working_days = NON_WORKING_DATE not in current_working_days
    scenario_exercises_the_split = holiday_message_is_in_a_recurring_blocker and holiday_excluded_from_working_days

    return [
        MetricResult(
            metric_id="GC11-arithmetic-mismatch-count",
            name="figures where the production weekly roll-up disagrees with an independent, from-scratch recomputation",
            measured=len(mismatches),
            target=0,
            comparator_name="equals",
            passed=equals(len(mismatches), 0),
            detail=(
                f"checked participation/trend, excluded_members, recurring_blockers, decisions, "
                f"unanswered_questions across a week containing one non-working day ({NON_WORKING_DATE.isoformat()}); "
                f"mismatched sections: {mismatches or 'none'}; omar this week: "
                f"{omar_trend.current.contributed_days}/{omar_trend.current.working_days} "
                f"working days, {len(production.recurring_blockers)} recurring blocker author(s)"
            ),
        ),
        MetricResult(
            metric_id="GC11-non-working-day-scenario-check",
            name="the declared holiday is excluded from the participation denominator but still inside the recurring-blocker window",
            measured=scenario_exercises_the_split,
            target=True,
            comparator_name="equals",
            passed=equals(scenario_exercises_the_split, True),
            detail=(
                f"holiday {NON_WORKING_DATE.isoformat()} in working_days_in_range={not holiday_excluded_from_working_days}, "
                f"in a recurring blocker's days={holiday_message_is_in_a_recurring_blocker}"
            ),
        ),
    ]


def register(registry: GoldenCaseRegistry) -> None:
    registry.register(
        GoldenCase(
            case_id="GC11",
            description=(
                "Weekly arithmetic reproducibility: every figure in the weekly roll-up recomputes by an "
                "independent implementation, for a week containing a declared non-working day (CHN-20)"
            ),
            measure_fn=_measure_gc11,
        )
    )
