"""
CHN-17: scheduled publishing, idempotent, per-channel local time (P1 Channel).

"First-publish approval means no channel ever receives an unexpected
bot post." This module is the actual job body a due channel's cron
fires (see scheduler.py for the clock): generate the digest, decide
whether sending it needs a human first, and if not, send it -- exactly
once, no matter how many times this function is called for the same
channel and day.

Two separate resources get two separate idempotency keys, on purpose:

  - f"{channel_id}:{date}:daily" -- the digest CONTENT. Already CHN-13's
    own key (generate_and_persist_daily_summary); regenerating today's
    digest before it is sent safely overwrites its content in place,
    same as it always has.

  - f"{channel_id}:{date}:daily_publish" -- the decision to SEND that
    content anywhere. A SPN-08 Proposal keyed on this is what "exactly
    one digest per channel per day" actually means for publishing:
    content can be regenerated any number of times right up until it is
    approved, but the proposal governing whether it goes out is created
    once and only once per channel per day.

First publish per channel requires approval; subsequent days run
unattended -- decided by DigestStore.has_ever_published(channel_id), a
question about every date this channel has ever published on, not just
today's. A channel's very first due day creates a pending proposal and
this job's own send attempt against it is refused (see below); a human
approves it the same way any other proposal is approved (SPN-08's own
approve()), and only then does a rerun of this job actually send. Every
later due day, this same job auto-approves its own proposal (via
AUTO_APPROVE_APPROVER_ID, an approver identity that is honest about
being the system rather than a person) and sends unattended in the same
run -- "no channel ever receives an unexpected bot post" is satisfied
once, at the channel's first publish, not re-litigated every day after.

No config field names a "designated summary channel" (ChannelConfig has
none), so this job publishes each channel's digest into that channel
itself -- see DECISION_LOG.md for this being a deliberate, visible scope
decision rather than a silently dropped requirement.

Sending itself is delegated to SPN-09's guarded_send() and an opaque
`publisher` (a duck-typed object with a post_channel_message(channel_id,
content) method -- CHN-22's own concern is building a real one; this
job only needs *something* with that shape, same as write_guard.py only
needs an opaque send_fn). This function calls guarded_send() on EVERY
run, whatever the proposal's current status -- it never short-circuits
around it for a pending, rejected, or already-applied proposal. That is
what makes CHN-18/GC6's own acceptance test true: "run the daily job
three times over the same day" produces exactly one write_log "sent"
row and two "refused" rows for the two suppressed reruns, because
guarded_send() itself is what writes every one of those rows -- see
DECISION_LOG.md for why an earlier version of this function shortcut
around guarded_send() for those statuses, and why that turned out to be
the wrong call once CHN-18 needed those suppressed attempts to actually
be visible in write_log. WriteRefusedError is caught here only to
translate SPN-09's one generic refusal into this job's own
more-specific JobResult status (awaiting_approval / rejected /
already_published) -- it is never used to skip calling guarded_send()
in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from p1.approval.proposals import APPLIED, APPROVED, PENDING, REJECTED, ProposalStore
from p1.approval.write_guard import WriteRefusedError, guarded_send
from p1.config.calendar import is_working_day
from p1.config.schema import ChannelConfig
from p1.prompts import PromptRegistry
from p1.reporting.daily_summary import generate_and_persist_daily_summary
from p1.storage.db import DEFAULT_DB_PATH
from p1.storage.digests_repo import DigestStore

# Used as approver_id for the subsequent-days auto-approval, so a
# write_log/proposals row never claims a human decided this -- it is
# always honestly attributable to the job itself, distinguishable at a
# glance from every approver_id a real person's approval ever sets.
AUTO_APPROVE_APPROVER_ID = "system:auto_approve_after_first_publish"

SKIPPED_NON_WORKING_DAY = "skipped_non_working_day"
AWAITING_APPROVAL = "awaiting_approval"
REJECTED_STATUS = "rejected"
PUBLISHED = "published"
ALREADY_PUBLISHED = "already_published"


@dataclass(frozen=True)
class JobResult:
    channel_id: str
    date: str
    status: str
    detail: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_daily_digest_job(
    channel_id: str,
    config: ChannelConfig,
    gateway,
    publisher,
    *,
    day: date_type | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    proposal_store: ProposalStore | None = None,
    digest_store: DigestStore | None = None,
    prompt_registry: PromptRegistry | None = None,
) -> JobResult:
    """Idempotent: safe to call any number of times for the same
    channel_id/day. `day` defaults to "today" in the channel's own
    timezone -- a demo's clock override passes it explicitly instead of
    letting this function ask a real clock, the same override mechanism
    scheduler.is_due() uses.
    """
    proposal_store = proposal_store or ProposalStore(db_path)
    digest_store = digest_store or DigestStore(db_path)
    resolved_day = day or datetime.now(ZoneInfo(config.timezone)).date()
    date_str = resolved_day.isoformat()

    if not is_working_day(resolved_day, config):
        return JobResult(channel_id, date_str, SKIPPED_NON_WORKING_DAY, "not a working day for this channel")

    # Regenerating today's content is always safe -- CHN-13's own
    # idempotency key means this never duplicates or drifts, whether
    # this is the first call of the day or the tenth.
    digest_result = generate_and_persist_daily_summary(
        channel_id, resolved_day, config, gateway, db_path=db_path, prompt_registry=prompt_registry,
    )

    publish_key = f"{channel_id}:{date_str}:daily_publish"
    proposal = proposal_store.get_by_idempotency_key(publish_key)

    # Computed on every call, whether or not a proposal already exists --
    # regenerating today's digest content is safe any number of times
    # (this function's own module docstring), and as of the fix below
    # that is no longer true only of the digests table's own row: a
    # still-pending proposal's payload is refreshed to match too, so
    # what a human eventually approves -- and what guarded_send() below
    # actually posts -- is never a stale snapshot from the moment this
    # proposal was first created.
    source_refs = sorted(
        {line.message_id for lines in digest_result.section_lines.values() for line in lines}
    )
    publish_payload = {
        "channel_id": channel_id,
        "date": date_str,
        "target_channel": channel_id,  # no summary-channel config field -- see module docstring
        "content": digest_result.content,
    }

    if proposal is None:
        # has_ever_published() is asked ONLY here, at the moment a
        # channel's publish proposal for this day is first created --
        # never again on a later rerun for the same day, since the
        # proposal itself (not this flag) is what governs every rerun
        # from here on.
        is_first_publish_ever = not digest_store.has_ever_published(channel_id)
        proposal = proposal_store.create(
            type="daily_digest_publish",
            payload=publish_payload,
            original_model_output=publish_payload,
            source_refs=source_refs,
            idempotency_key=publish_key,
        )
        if not is_first_publish_ever:
            proposal = proposal_store.approve(proposal.id, approver_id=AUTO_APPROVE_APPROVER_ID)
        # If this IS the first publish ever, proposal is left PENDING --
        # the guarded_send() call below refuses it (and logs that
        # refusal to write_log) exactly like any other pending proposal
        # would, rather than this function special-casing "brand new"
        # as a case that never even attempts a send.
    elif proposal.status == PENDING:
        # Still awaiting a human decision -- discovered 2026-09-19: a
        # rerun here used to leave this proposal's payload frozen at
        # whatever existed the moment it was first created, even though
        # digest_result.content just above was freshly regenerated from
        # this call's own messages. refresh_payload() is a no-op-safe
        # replacement restricted to pending proposals only (see its own
        # docstring) -- once approved, rejected, or applied, this branch
        # is never reached again (the elif above only matches PENDING),
        # so a decided proposal's payload is never touched here.
        proposal = proposal_store.refresh_payload(
            proposal.id, payload=publish_payload, source_refs=source_refs,
        )
    elif proposal.status == APPROVED and proposal.approver_id == AUTO_APPROVE_APPROVER_ID:
        # Approved by the system itself (no human vetted this wording) but never
        # sent -- a failed send being retried later. Carry current content, not
        # the snapshot from the first attempt. See ProposalStore.refresh_payload.
        proposal = proposal_store.refresh_payload(
            proposal.id, payload=publish_payload, source_refs=source_refs,
            also_if_approved_by=AUTO_APPROVE_APPROVER_ID,
        )

    def send_fn():
        fresh = proposal_store.get(proposal.id)
        return publisher.post_channel_message(fresh.payload["target_channel"], fresh.payload["content"])

    try:
        guarded_send(
            proposal.id,
            action_type="channel_post",
            target=channel_id,
            send_fn=send_fn,
            store=proposal_store,
            db_path=db_path,
        )
    except WriteRefusedError:
        # guarded_send() has already logged this refusal to write_log --
        # this only translates its one generic refusal into this job's
        # own more specific status, by asking the store what the
        # proposal's status actually is now.
        current_status = proposal_store.get(proposal.id).status
        if current_status == PENDING:
            return JobResult(channel_id, date_str, AWAITING_APPROVAL, "awaiting human approval")
        if current_status == REJECTED:
            return JobResult(channel_id, date_str, REJECTED_STATUS, "publish was rejected for this channel and day")
        if current_status == APPLIED:
            return JobResult(channel_id, date_str, ALREADY_PUBLISHED, "already sent for this channel and day")
        raise  # pragma: no cover -- defensive; no other status refuses

    digest_store.mark_published(
        idempotency_key=f"{channel_id}:{date_str}:daily",
        published_at=_now_iso(),
    )
    return JobResult(channel_id, date_str, PUBLISHED, "sent")
