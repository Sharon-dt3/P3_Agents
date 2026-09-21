"""
CHN-23: escalate to the channel owner (P1 Channel).

"After N consecutive missed update days (N from config), escalate to
the configured channel owner with the evidence: the dates, the window
applied, and what was and was not posted. The first escalation for any
person requires approval. Escalation is a private message to the
owner, never a channel post." This module is the job body that, for
one channel and one day, looks at CHN-10's own non-responder ledger
across a run of consecutive working days and turns a threshold-length
missed-update streak into a dated evidence bundle sent to the channel
owner -- gated by the exact same proposal/write-guard machinery
CHN-17's daily digest and CHN-21's nudges already proved out.

"The evidence bundle is the point -- an escalation without dates and
message IDs is an accusation" is this row's own framing, and it is
literal here: the escalation's payload carries the full list of missed
days, each one's ledger state (no_message vs. posted_no_update, with
message IDs for the latter), and the update window that was applied --
never a bare "N has been quiet" claim with nothing behind it.

Delivery is a Teams concern: this job only calls
publisher.post_direct_message(config.channel_owner_id, content) -- the
same TeamsPublisher method CHN-21's nudges use, just addressed to the
owner instead of the non-responder themselves. guarded_send()'s own
docstring already anticipated this row's call shape:
action_type="escalation"/target=owner_id -- target is the message's
recipient (the owner), not the person the escalation is about, the
same convention nudges use (target=member_id, the nudge's recipient).

Four separate guarantees layer on top of each other here, each one
load-bearing on its own:

1. Threshold-driven, computed independently per member -- a member is
   only a candidate once _streak_dates_ending_at() has walked backward
   from `day` over consecutive WORKING days (skipping weekends/
   non_working_dates the same way the ledger itself does) and found at
   least config.escalation_threshold_days of them where this person's
   ledger state was no_message or posted_no_update, with no break. The
   walk stops the instant it hits a day the person contributed (no
   ledger record at all that day) or a day marked EXCLUDED -- neither
   ever counts toward the streak, and either resets it.

2. Never the excluded, checked twice, independently -- exactly CHN-21's
   own pattern, and this time built correctly from the start rather
   than needing the CHN-21 bug-fix repeated: build_ledger() already
   marks an on-leave member's non-response as EXCLUDED rather than
   no_message/posted_no_update, so they are never a streak candidate in
   the first place. Separately, run_escalation_job's own per-member
   loop checks every remaining candidate's member_id against
   config.exceptions again, directly, before a streak is ever walked
   for them -- the actual second layer, exercised by a test that hands
   this job a deliberately mislabelled record to prove it, not a copy
   of the first filter that would just agree with it every time. See
   DECISION_LOG.md.

3. Nudge precedes escalation -- a real, enforced gate, not merely a
   suggested job-running order. A member is never escalated, however
   long their streak, unless NudgeStore.has_ever_been_nudged() is
   already True for them in this channel. A channel that never turns
   nudging on (nudge_enabled=False, CHN-21's own default) therefore
   never produces an escalation either, for anyone -- there is no
   separate "escalation enabled" flag in ChannelConfig because this
   gate already makes escalation strictly downstream of nudging. See
   DECISION_LOG.md for why this was chosen over a second config flag.

4. Per-streak cap, per-person approval gating -- exactly CHN-17/18/21's
   idempotency-key + proposal-status pattern, keyed on (channel_id,
   member_id, streak_start_date) instead of (channel_id, date) or
   (channel_id, member_id, date, sequence). Because the key is the
   streak's OWN start date, not the day the job happens to run on, a
   streak that keeps growing past the threshold (day 4, day 5, ...) is
   never re-escalated -- guarded_send() reports ALREADY_SENT the same
   way a repeat digest publish attempt does. Only once the person
   actually contributes again (breaking the streak) and then misses
   the threshold again does a NEW streak_start_date produce a new,
   independent escalation. EscalationStore.has_ever_been_escalated() --
   scoped per person, not per streak -- decides whether THAT escalation
   auto-approves or is left pending, the same "asked once, at creation"
   posture as CHN-21's has_ever_been_nudged() check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from pathlib import Path

from p1.approval.proposals import APPLIED, PENDING, REJECTED, ProposalStore
from p1.approval.write_guard import WriteRefusedError, guarded_send
from p1.config.calendar import is_working_day
from p1.config.schema import ChannelConfig
from p1.participation.ledger import (
    EXCLUDED,
    NO_MESSAGE,
    POSTED_NO_UPDATE,
    ParticipationRecord,
    build_ledger,
)
from p1.storage.db import DEFAULT_DB_PATH, get_connection
from p1.storage.escalations_repo import EscalationStore
from p1.storage.nudges_repo import NudgeStore

# Same honesty convention as CHN-17/21's AUTO_APPROVE_APPROVER_ID: a
# write_log/proposals row auto-approved by this job never claims a
# human decided it.
AUTO_APPROVE_APPROVER_ID = "system:auto_approve_after_first_escalation"

# A safety bound on how far back _streak_dates_ending_at() will ever
# walk, in calendar days (so it also covers the weekends/non-working
# days it skips over without counting against the budget in a useful
# way). Comfortably covers any real streak a several-day threshold
# would ever need to prove; it exists only to guarantee termination if
# a channel's message history is missing entirely, not because a real
# streak is expected to approach it.
_MAX_STREAK_LOOKBACK_CALENDAR_DAYS = 120

SKIPPED_NON_WORKING_DAY = "skipped_non_working_day"
EXCLUDED_STATUS = "excluded"
BELOW_THRESHOLD = "below_threshold"
AWAITING_NUDGE = "awaiting_nudge"
AWAITING_APPROVAL = "awaiting_approval"
REJECTED_STATUS = "rejected"
ALREADY_SENT = "already_sent"
SENT = "sent"


@dataclass(frozen=True)
class EscalationResult:
    channel_id: str
    member_id: str | None  # None only for a channel-level result (non-working day)
    date: str
    status: str
    detail: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _eligible_candidates(records: list[ParticipationRecord]) -> list[ParticipationRecord]:
    """Only the ledger's own EXCLUDED state is filtered here -- see
    guarantee 2 in the module docstring. This function deliberately
    does NOT re-check config.exceptions itself: that second, independent
    check happens once, in run_escalation_job's own per-member loop
    below, before a streak is ever walked for that person."""
    return [record for record in records if record.state != EXCLUDED]


def _streak_dates_ending_at(
    channel_id: str,
    member_id: str,
    day: date_type,
    config: ChannelConfig,
    *,
    db_path: str | Path,
    ledger_cache: dict[date_type, list[ParticipationRecord]],
) -> list[date_type]:
    """The unbroken run of working days, oldest first, ending at and
    including `day`, on which this member's ledger state was
    no_message or posted_no_update. Stops at the first working day the
    member contributed (no ledger record at all that day -- a
    contributor is never written to the ledger), or was EXCLUDED that
    day, or after _MAX_STREAK_LOOKBACK_CALENDAR_DAYS calendar days.

    ledger_cache is shared across every member evaluated in the same
    run_escalation_job() call, and across every day's build_ledger()
    call within that: a given day's ledger is computed at most once per
    run, however many members' streaks need to look at it.
    """
    dates: list[date_type] = []
    current = day
    for _ in range(_MAX_STREAK_LOOKBACK_CALENDAR_DAYS):
        if not is_working_day(current, config):
            current = current - timedelta(days=1)
            continue

        if current not in ledger_cache:
            ledger_cache[current] = build_ledger(channel_id, current, config, db_path=db_path)

        record = next((r for r in ledger_cache[current] if r.member_id == member_id), None)
        if record is None or record.state not in (NO_MESSAGE, POSTED_NO_UPDATE):
            break  # contributed that day, or was EXCLUDED -- either resets the streak

        dates.append(current)
        current = current - timedelta(days=1)

    dates.reverse()  # oldest first
    return dates


def _evidence_days(
    member_id: str,
    streak_dates: list[date_type],
    ledger_cache: dict[date_type, list[ParticipationRecord]],
) -> list[dict]:
    days = []
    for d in streak_dates:
        record = next(r for r in ledger_cache[d] if r.member_id == member_id)
        days.append(
            {
                "date": d.isoformat(),
                "state": record.state,
                "evidence_message_ids": list(record.evidence_message_ids),
            }
        )
    return days


def _resolve_display_name(member_id: str, *, db_path: str | Path) -> str:
    """Looks up this person's current members.display_name for the
    escalation message the channel owner reads -- a real name once a
    human has corrected the auto-registered placeholder (see
    messages_repo.py's own _ensure_member_exists docstring), still just
    their AAD id otherwise, since that is exactly what auto-registration
    stores until then. 2026-09-21 fix (see DECISION_LOG.md): this used
    to interpolate member_id directly into the message text, so a
    corrected members.display_name row had no path to ever showing up
    here -- the one place in this whole pipeline that actually names a
    specific person for someone else (the channel owner) to read. Falls
    back to member_id itself if the member row is somehow missing
    entirely (should not happen -- every author is auto-registered on
    ingest, see messages_repo.py -- but this message must never crash
    over a missing name)."""
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT display_name FROM members WHERE id = ?", (member_id,)).fetchone()
    finally:
        conn.close()
    return row["display_name"] if row and row["display_name"] else member_id


def _render_escalation_message(config: ChannelConfig, display_name: str, days: list[dict]) -> str:
    """A fixed, deterministic template -- never a model call. Every
    date in the streak is listed with what the ledger actually says for
    that day, plus the update window that was applied -- "an escalation
    without dates and message IDs is an accusation" is this row's own
    framing, and this is what makes that literally false here.

    display_name is whatever _resolve_display_name() resolved -- a real
    name when one is known, the bare member_id otherwise -- this
    function itself has no opinion on which; it just renders whatever
    string it is given."""
    window = (
        f"{config.update_window_start.strftime('%H:%M')}-"
        f"{config.update_window_end.strftime('%H:%M')} {config.timezone}"
    )
    lines = []
    for d in days:
        if d["state"] == POSTED_NO_UPDATE:
            ids = ", ".join(d["evidence_message_ids"]) or "none"
            lines.append(f"  - {d['date']}: posted, but nothing counted as an update (message id(s): {ids})")
        else:
            lines.append(f"  - {d['date']}: no message at all")
    day_list = "\n".join(lines)
    return (
        f"Hi! {display_name} has missed {len(days)} consecutive working day(s) of updates in "
        f"{config.display_name} (update window {window}):\n{day_list}\n"
        "Flagging in case a check-in would help -- they were already nudged directly before this."
    )


def run_escalation_job(
    channel_id: str,
    config: ChannelConfig,
    publisher,
    *,
    day: date_type | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    proposal_store: ProposalStore | None = None,
    escalation_store: EscalationStore | None = None,
    nudge_store: NudgeStore | None = None,
    ledger_records: list[ParticipationRecord] | None = None,
) -> list[EscalationResult]:
    """Idempotent and streak-aware: safe to call any number of times for
    the same channel_id/day, and safe to call every working day of a
    growing streak without ever re-escalating the same unbroken streak
    twice. `day` defaults to "today" the same way run_nudge_job's own
    `day` parameter does.

    `ledger_records`, when given, is used instead of calling
    build_ledger() for `day` itself (production callers never pass it);
    it exists so a test can hand this job records that deliberately
    mislabel an excepted member, to prove this function's own
    per-member exceptions check (guarantee 2 in the module docstring)
    holds even when the ledger itself cannot be trusted. Any day this
    function needs to walk back BEYOND `day` is still computed for real
    via build_ledger().
    """
    proposal_store = proposal_store or ProposalStore(db_path)
    escalation_store = escalation_store or EscalationStore(db_path)
    nudge_store = nudge_store or NudgeStore(db_path)
    resolved_day = day or datetime.now(timezone.utc).date()
    date_str = resolved_day.isoformat()

    if not is_working_day(resolved_day, config):
        return [
            EscalationResult(
                channel_id, None, date_str, SKIPPED_NON_WORKING_DAY, "not a working day for this channel",
            )
        ]

    records = ledger_records if ledger_records is not None else build_ledger(
        channel_id, resolved_day, config, db_path=db_path,
    )
    eligible = _eligible_candidates(records)
    ledger_cache: dict[date_type, list[ParticipationRecord]] = {resolved_day: records}

    excepted = {e.member_id for e in config.exceptions}
    results: list[EscalationResult] = []
    for record in sorted(eligible, key=lambda r: r.member_id):
        # The real, always-executed exceptions check -- independent of
        # whatever state the ledger record arrived with. See guarantee
        # 2 in the module docstring and DECISION_LOG.md.
        if record.member_id in excepted:
            results.append(
                EscalationResult(
                    channel_id, record.member_id, date_str, EXCLUDED_STATUS, "member is on the exceptions list",
                )
            )
            continue

        result = _evaluate_member(
            channel_id, record.member_id, resolved_day, config, publisher, date_str,
            proposal_store=proposal_store, escalation_store=escalation_store, nudge_store=nudge_store,
            db_path=db_path, ledger_cache=ledger_cache,
        )
        results.append(result)

    return results


def _evaluate_member(
    channel_id: str,
    member_id: str,
    day: date_type,
    config: ChannelConfig,
    publisher,
    date_str: str,
    *,
    proposal_store: ProposalStore,
    escalation_store: EscalationStore,
    nudge_store: NudgeStore,
    db_path: str | Path,
    ledger_cache: dict[date_type, list[ParticipationRecord]],
) -> EscalationResult:
    streak_dates = _streak_dates_ending_at(
        channel_id, member_id, day, config, db_path=db_path, ledger_cache=ledger_cache,
    )

    if len(streak_dates) < config.escalation_threshold_days:
        return EscalationResult(
            channel_id, member_id, date_str, BELOW_THRESHOLD,
            f"missed {len(streak_dates)} consecutive working day(s); "
            f"threshold is {config.escalation_threshold_days}",
        )

    if not nudge_store.has_ever_been_nudged(channel_id, member_id):
        return EscalationResult(
            channel_id, member_id, date_str, AWAITING_NUDGE,
            "not yet nudged in this channel -- nudge precedes escalation",
        )

    streak_start = streak_dates[0]
    escalation_key = f"{channel_id}:{member_id}:{streak_start.isoformat()}"
    proposal = proposal_store.get_by_idempotency_key(escalation_key)

    if proposal is None:
        days_detail = _evidence_days(member_id, streak_dates, ledger_cache)
        display_name = _resolve_display_name(member_id, db_path=db_path)
        content = _render_escalation_message(config, display_name, days_detail)
        payload = {
            "channel_id": channel_id,
            "member_id": member_id,
            "streak_start_date": streak_start.isoformat(),
            "streak_end_date": day.isoformat(),
            "days": days_detail,
            "content": content,
        }
        source_refs = [mid for d in days_detail for mid in d["evidence_message_ids"]]
        # has_ever_been_escalated() is asked ONLY here, at the moment
        # this streak's escalation proposal is first created -- the
        # same "asked once, at creation" posture CHN-21's
        # has_ever_been_nudged() check already established.
        is_first_escalation_ever = not escalation_store.has_ever_been_escalated(channel_id, member_id)
        proposal = proposal_store.create(
            type="escalation",
            payload=payload,
            original_model_output=payload,
            source_refs=source_refs,
            idempotency_key=escalation_key,
        )
        escalation_store.record(
            channel_id=channel_id, member_id=member_id, streak_start_date=streak_start.isoformat(),
            date=date_str, idempotency_key=escalation_key, proposal_id=proposal.id,
        )
        if not is_first_escalation_ever:
            proposal = proposal_store.approve(proposal.id, approver_id=AUTO_APPROVE_APPROVER_ID)
        # If this IS this person's first escalation ever, proposal is
        # left PENDING -- guarded_send() below refuses it (and logs
        # that refusal) exactly like run_nudge_job's own first-nudge
        # case, rather than this function special-casing "brand new."

    def send_fn():
        fresh = proposal_store.get(proposal.id)
        return publisher.post_direct_message(config.channel_owner_id, fresh.payload["content"])

    try:
        guarded_send(
            proposal.id,
            action_type="escalation",
            target=config.channel_owner_id,
            send_fn=send_fn,
            store=proposal_store,
            db_path=db_path,
        )
    except WriteRefusedError:
        current_status = proposal_store.get(proposal.id).status
        if current_status == PENDING:
            return EscalationResult(channel_id, member_id, date_str, AWAITING_APPROVAL, "awaiting human approval")
        if current_status == REJECTED:
            return EscalationResult(channel_id, member_id, date_str, REJECTED_STATUS, "this escalation was rejected")
        if current_status == APPLIED:
            return EscalationResult(
                channel_id, member_id, date_str, ALREADY_SENT, "already escalated for this streak",
            )
        raise  # pragma: no cover -- defensive; no other status refuses

    escalation_store.mark_sent(idempotency_key=escalation_key, sent_at=_now_iso())
    return EscalationResult(channel_id, member_id, date_str, SENT, "escalated")
