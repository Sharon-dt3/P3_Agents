"""
CHN-21: nudge non-responders -- opt-in, capped, never the excluded (P1 Channel).

"OFF BY DEFAULT, enabled per channel... Members on the exceptions list
are never nudged... The first nudge to any given person requires
approval; thereafter within cap it runs unattended." This module is
the job body that, for one channel and one day, looks at CHN-11's own
non-responder ledger and turns each eligible non-responder into a
polite reminder -- gated by the exact same proposal/write-guard
machinery CHN-17's daily digest already proved out, just re-scoped from
"once per channel per day" to "up to nudge_cap_per_day times per person
per day."

Eligibility and the cap are Python, and stay in code (this row's own
framing) -- there is no model call anywhere in this module, and the
reminder text itself is a fixed, deterministic template, not generated.
Delivery is a Teams concern: this job only calls
publisher.post_direct_message(member_id, content), the second method on
CHN-22's own TeamsPublisher interface, the same seam daily_job.py
already uses for publisher.post_channel_message -- CHN-22's LogPublisher
and PowerAutomateTeamsPublisher are what give that a real body.

Three separate guarantees layer on top of each other here, each one
load-bearing on its own:

1. OFF BY DEFAULT -- config.nudge_enabled is checked first, before the
   ledger is even built. A channel that never opts in produces zero
   nudge proposals, ever, regardless of how many non-responders it has.

2. Never the excluded, checked twice, independently -- CHN-11's own
   p1.participation.ledger.build_ledger() already marks an on-leave
   (config.exceptions) member's non-response as EXCLUDED rather than
   NO_MESSAGE/POSTED_NO_UPDATE, so they are never a nudge *candidate* in
   the first place. Separately, and not merely as a restatement of that
   same filter, run_nudge_job's own per-member loop checks every
   remaining candidate's member_id against config.exceptions again,
   directly, right before a proposal could ever be created for them --
   the actual second layer, exercised by a test that hands this job a
   deliberately mislabelled record to prove it, not a copy of the first
   filter that would just agree with it every time. See DECISION_LOG.md
   for why this is belt-and-suspenders rather than trusting one layer
   alone, matching this row's own "never... under any path" wording.

3. Per-person cap, per-person approval gating -- exactly CHN-17/18's
   idempotency-key + proposal-status pattern, just keyed on
   (channel_id, member_id, date, sequence) instead of
   (channel_id, date). NudgeStore.sent_count_for_day() is checked
   BEFORE any proposal is created for this run: once a person has
   received nudge_cap_per_day nudges today, no further proposal is even
   attempted, so the cap holds no matter how many times this job is
   called for the same channel and day (see CHN-18/GC6's identical
   reasoning for the daily digest). NudgeStore.has_ever_been_nudged()
   -- scoped per person, not per channel -- decides whether THIS
   person's next nudge auto-approves or is left pending; a cold-start
   person's every nudge attempt today is refused and logged until a
   human approves the first one, the same "no channel ever receives an
   unexpected bot post" story CHN-17 already tells, told here about a
   person instead of a channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path

from p1.approval.proposals import APPLIED, PENDING, REJECTED, ProposalStore
from p1.approval.write_guard import WriteRefusedError, guarded_send
from p1.config.calendar import is_working_day
from p1.config.schema import ChannelConfig
from p1.participation.ledger import (
    EXCLUDED,
    POSTED_NO_UPDATE,
    ParticipationRecord,
    build_ledger,
)
from p1.storage.db import DEFAULT_DB_PATH
from p1.storage.nudges_repo import NudgeStore

# Same honesty convention as CHN-17's AUTO_APPROVE_APPROVER_ID: a
# write_log/proposals row auto-approved by this job never claims a
# human decided it.
AUTO_APPROVE_APPROVER_ID = "system:auto_approve_after_first_nudge"

DISABLED = "disabled"
SKIPPED_NON_WORKING_DAY = "skipped_non_working_day"
EXCLUDED_STATUS = "excluded"
CAP_REACHED = "cap_reached"
AWAITING_APPROVAL = "awaiting_approval"
REJECTED_STATUS = "rejected"
ALREADY_SENT = "already_sent"
SENT = "sent"


@dataclass(frozen=True)
class NudgeResult:
    channel_id: str
    member_id: str | None  # None only for a channel-level result (disabled / non-working day)
    date: str
    status: str
    detail: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_nudge_message(config: ChannelConfig, state: str) -> str:
    """A fixed, deterministic template -- never a model call. Which of
    the two ledger states triggered the nudge changes the wording
    slightly (chattered-but-no-update vs. said nothing at all), but the
    text itself is not generated."""
    if state == POSTED_NO_UPDATE:
        return (
            f"Hi! We saw you post in {config.display_name} today, but didn't see an update, blocker, "
            "decision or question we could log for the day. No pressure -- just checking in case "
            "something's blocking you or there's a quick update to share."
        )
    return (
        f"Hi! We haven't seen a message from you in {config.display_name} today. No worries if "
        "you're heads-down -- just a friendly nudge in case an update slipped through."
    )


def _eligible_non_responders(records: list[ParticipationRecord]) -> list[ParticipationRecord]:
    """Only the ledger's own EXCLUDED state is filtered here -- an
    excepted member's non-response is never NO_MESSAGE/POSTED_NO_UPDATE
    in the first place (see build_ledger()). This function deliberately
    does NOT re-check config.exceptions itself: that second, independent
    check happens once, in run_nudge_job's own per-member loop below,
    right before a proposal could ever be created for that person --
    the actual enforcement point, not a second copy of this filter that
    would just silently agree with it every time."""
    return [record for record in records if record.state != EXCLUDED]


def run_nudge_job(
    channel_id: str,
    config: ChannelConfig,
    publisher,
    *,
    day: date_type | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    proposal_store: ProposalStore | None = None,
    nudge_store: NudgeStore | None = None,
    ledger_records: list[ParticipationRecord] | None = None,
) -> list[NudgeResult]:
    """Idempotent and cap-respecting: safe to call any number of times
    for the same channel_id/day. `day` defaults to "today" the same way
    run_daily_digest_job's own `day` parameter does.

    `ledger_records`, when given, is used instead of calling
    build_ledger() -- production callers never pass it; it exists so a
    test can hand this job records that deliberately mislabel an
    excepted member, to prove this function's own per-member exceptions
    check (guarantee 2 in the module docstring) holds even when the
    ledger itself cannot be trusted.
    """
    proposal_store = proposal_store or ProposalStore(db_path)
    nudge_store = nudge_store or NudgeStore(db_path)
    resolved_day = day or datetime.now(timezone.utc).date()
    date_str = resolved_day.isoformat()

    if not config.nudge_enabled:
        return [NudgeResult(channel_id, None, date_str, DISABLED, "nudges are not enabled for this channel")]

    if not is_working_day(resolved_day, config):
        return [
            NudgeResult(
                channel_id, None, date_str, SKIPPED_NON_WORKING_DAY, "not a working day for this channel",
            )
        ]

    records = ledger_records if ledger_records is not None else build_ledger(
        channel_id, resolved_day, config, db_path=db_path,
    )
    eligible = _eligible_non_responders(records)

    excepted = {e.member_id for e in config.exceptions}
    results: list[NudgeResult] = []
    for record in sorted(eligible, key=lambda r: r.member_id):
        # The real, always-executed exceptions check -- independent of
        # whatever state the ledger record arrived with. build_ledger()
        # never emits NO_MESSAGE/POSTED_NO_UPDATE for an excepted member,
        # but this job does not take that on faith: every candidate is
        # checked against config.exceptions directly, right here, before
        # a proposal could ever exist for them. See DECISION_LOG.md.
        if record.member_id in excepted:
            results.append(
                NudgeResult(channel_id, record.member_id, date_str, EXCLUDED_STATUS, "member is on the exceptions list")
            )
            continue

        result = _run_one_member(
            channel_id, record, config, publisher, date_str,
            proposal_store=proposal_store, nudge_store=nudge_store, db_path=db_path,
        )
        results.append(result)

    return results


def _run_one_member(
    channel_id: str,
    record: ParticipationRecord,
    config: ChannelConfig,
    publisher,
    date_str: str,
    *,
    proposal_store: ProposalStore,
    nudge_store: NudgeStore,
    db_path: str | Path,
) -> NudgeResult:
    member_id = record.member_id

    sent_count_today = nudge_store.sent_count_for_day(channel_id, member_id, date_str)
    if sent_count_today >= config.nudge_cap_per_day:
        return NudgeResult(
            channel_id, member_id, date_str, CAP_REACHED,
            f"cap of {config.nudge_cap_per_day} nudge(s)/day already reached for this person today",
        )

    sequence = sent_count_today + 1
    nudge_key = f"{channel_id}:{member_id}:{date_str}:{sequence}"
    proposal = proposal_store.get_by_idempotency_key(nudge_key)

    if proposal is None:
        content = _render_nudge_message(config, record.state)
        payload = {
            "channel_id": channel_id,
            "member_id": member_id,
            "date": date_str,
            "state": record.state,
            "content": content,
        }
        # has_ever_been_nudged() is asked ONLY here, at the moment this
        # person's nudge proposal for this (day, sequence) is first
        # created -- the same "asked once, at creation" posture
        # CHN-17's has_ever_published() check already established.
        is_first_nudge_ever = not nudge_store.has_ever_been_nudged(channel_id, member_id)
        proposal = proposal_store.create(
            type="nudge",
            payload=payload,
            original_model_output=payload,
            source_refs=list(record.evidence_message_ids),
            idempotency_key=nudge_key,
        )
        nudge_store.record(
            channel_id=channel_id, member_id=member_id, date=date_str,
            idempotency_key=nudge_key, proposal_id=proposal.id,
        )
        if not is_first_nudge_ever:
            proposal = proposal_store.approve(proposal.id, approver_id=AUTO_APPROVE_APPROVER_ID)
        # If this IS this person's first nudge ever, proposal is left
        # PENDING -- guarded_send() below refuses it (and logs that
        # refusal) exactly like run_daily_digest_job's own first-publish
        # case, rather than this function special-casing "brand new."

    def send_fn():
        fresh = proposal_store.get(proposal.id)
        return publisher.post_direct_message(fresh.payload["member_id"], fresh.payload["content"])

    try:
        guarded_send(
            proposal.id,
            action_type="nudge",
            target=member_id,
            send_fn=send_fn,
            store=proposal_store,
            db_path=db_path,
        )
    except WriteRefusedError:
        current_status = proposal_store.get(proposal.id).status
        if current_status == PENDING:
            return NudgeResult(channel_id, member_id, date_str, AWAITING_APPROVAL, "awaiting human approval")
        if current_status == REJECTED:
            return NudgeResult(channel_id, member_id, date_str, REJECTED_STATUS, "this nudge was rejected")
        if current_status == APPLIED:
            return NudgeResult(channel_id, member_id, date_str, ALREADY_SENT, "already sent for this person today")
        raise  # pragma: no cover -- defensive; no other status refuses

    nudge_store.mark_sent(idempotency_key=nudge_key, sent_at=_now_iso())
    return NudgeResult(channel_id, member_id, date_str, SENT, "sent")
