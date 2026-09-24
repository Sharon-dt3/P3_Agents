"""
Scheduled publishing of the weekly roll-up (CHN-19/20 content, CHN-17-style
delivery): generate the week's roll-up, decide whether sending it needs a
human first, and if not, send it -- exactly once per channel per week.

Deliberately the same shape and the same guarantees as
p1.publishing.daily_job.run_daily_digest_job, reusing its JobResult and
status vocabulary rather than inventing a second one:

  - f"{channel_id}:{week_end}:weekly" -- the roll-up CONTENT (already
    generate_and_persist_weekly_rollup's own key); regenerating it before
    it is sent safely overwrites in place.
  - f"{channel_id}:{week_end}:weekly_publish" -- the decision to SEND it. A
    SPN-08 Proposal keyed on this is what "exactly one roll-up per
    channel per week" means; content may be regenerated any number of
    times until approved, the proposal is created once.

The first weekly roll-up ever sent to a channel requires a human's
approval (DigestStore.has_ever_published_type(channel, "weekly") is
False), even though the channel has long had daily digests published: a
weekly roll-up is a new kind of message, and "no channel ever receives an
unexpected bot post" applies per kind of post. Every later week runs
unattended, approved by the same honest system approver id the daily
digest uses. A human approves the first one the same way as any other
proposal, then re-runs this job (scripts/run_live_weekly_p1_agent_test.py)
to send it -- the scheduler fires once a week, so it does not retry on its
own.

Sending is delegated to SPN-09's guarded_send() on EVERY run, whatever the
proposal's status, so suppressed reruns are visible in write_log exactly
like the daily digest's.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from p1.approval.proposals import APPLIED, PENDING, REJECTED, ProposalStore
from p1.approval.write_guard import WriteRefusedError, guarded_send
from p1.config.schema import ChannelConfig
from p1.prompts import PromptRegistry
from p1.publishing.daily_job import (
    ALREADY_PUBLISHED,
    AUTO_APPROVE_APPROVER_ID,
    AWAITING_APPROVAL,
    PUBLISHED,
    REJECTED_STATUS,
    SKIPPED_NON_WORKING_DAY,
    JobResult,
    _now_iso,
)
from p1.reporting.weekly_summary import generate_and_persist_weekly_rollup
from p1.storage.db import DEFAULT_DB_PATH
from p1.storage.digests_repo import DigestStore

WEEKLY_DIGEST_TYPE = "weekly"


def run_weekly_rollup_job(
    channel_id: str,
    config: ChannelConfig,
    gateway,
    publisher,
    *,
    week_end: date_type | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    proposal_store: ProposalStore | None = None,
    digest_store: DigestStore | None = None,
    prompt_registry: PromptRegistry | None = None,
) -> JobResult:
    """Idempotent: safe to call any number of times for the same
    channel_id/week_end. `week_end` defaults to today in the channel's own
    timezone -- the scheduler fires this on the channel's configured
    weekly_digest_day, so "today" is that day, the last day of the week
    being summarised."""
    proposal_store = proposal_store or ProposalStore(db_path)
    digest_store = digest_store or DigestStore(db_path)
    resolved_end = week_end or datetime.now(ZoneInfo(config.timezone)).date()
    date_str = resolved_end.isoformat()

    if resolved_end in config.non_working_dates:
        return JobResult(channel_id, date_str, SKIPPED_NON_WORKING_DAY, "week-end date is a configured non-working date")

    result = generate_and_persist_weekly_rollup(
        channel_id, resolved_end, config, gateway, db_path=db_path, prompt_registry=prompt_registry,
    )

    publish_key = f"{channel_id}:{date_str}:weekly_publish"
    proposal = proposal_store.get_by_idempotency_key(publish_key)

    source_refs = sorted(
        {fact.message_id for fact in [*result.facts.decisions, *result.facts.unanswered_questions]}
    )
    publish_payload = {
        "channel_id": channel_id,
        "week_end": date_str,
        "target_channel": channel_id,
        "content": result.content,
    }

    if proposal is None:
        is_first_weekly_ever = not digest_store.has_ever_published_type(channel_id, WEEKLY_DIGEST_TYPE)
        proposal = proposal_store.create(
            type="weekly_rollup_publish",
            payload=publish_payload,
            original_model_output=publish_payload,
            source_refs=source_refs,
            idempotency_key=publish_key,
        )
        if not is_first_weekly_ever:
            proposal = proposal_store.approve(proposal.id, approver_id=AUTO_APPROVE_APPROVER_ID)
    elif proposal.status == PENDING:
        proposal = proposal_store.refresh_payload(proposal.id, payload=publish_payload, source_refs=source_refs)

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
        current_status = proposal_store.get(proposal.id).status
        if current_status == PENDING:
            return JobResult(channel_id, date_str, AWAITING_APPROVAL, "awaiting human approval")
        if current_status == REJECTED:
            return JobResult(channel_id, date_str, REJECTED_STATUS, "publish was rejected for this channel and week")
        if current_status == APPLIED:
            return JobResult(channel_id, date_str, ALREADY_PUBLISHED, "already sent for this channel and week")
        raise  # pragma: no cover -- defensive; no other status refuses

    digest_store.mark_published(
        idempotency_key=f"{channel_id}:{date_str}:weekly",
        published_at=_now_iso(),
    )
    return JobResult(channel_id, date_str, PUBLISHED, "sent")
