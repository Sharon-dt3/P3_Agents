"""
CHN-25: the one approval + config service both surfaces call (P1 Channel).

"Approving from Teams and from the fallback surface produce identical
audit records - proving the gate lives in the service, not the UI" --
this row's own acceptance test, made literally true here rather than
merely asserted: the Copilot Studio connector
(p1.adapters.copilot_studio_connector) and the Streamlit fallback
(app/approval_dashboard.py) both call list_pending_approvals(),
approve_and_send(), and reject() below, directly, with no surface-
specific parameter anywhere in their signatures. Neither surface ever
touches ProposalStore, write_guard, or ChannelConfigStore itself --
this module is the only thing standing between either one and the
data, so there is no code path by which one surface could get a
different answer, a different write_log row, or a different validation
outcome than the other. See tests/unit/test_copilot_studio_connector.py
for the equivalence proof this claim rests on, and
tests/unit/test_approval_dashboard_app.py for the same proof driven
through the actual Streamlit widgets, not just this module directly.

approve_and_send() does two things a bare ProposalStore.approve() call
does not: it writes one `audit` row recording the human decision itself
(actor, "proposal.approved", the proposal's id and type) -- a record of
who decided, independent of write_guard's own write_log, which only
ever records send ATTEMPTS -- and it immediately re-attempts delivery
via the same guarded_send() every job already routes through, using a
per-proposal-type resend plan that reads back exactly the fields the
job that created the proposal itself wrote (see _resend_plan below).
That is what makes clicking "Approve" actually send the message in the
same call, rather than silently waiting for that channel's job to
happen to run again.

Every failure mode guarded_send()/ProposalStore can raise is caught
here and turned into an ActionResult rather than an exception reaching
either surface: an already-decided proposal (IllegalTransitionError,
e.g. a second click), a refused send (WriteRefusedError, should not
happen immediately after a successful approve() but handled the same
way write_guard's own docstring insists on -- no ambiguous case ever
results in treating a send as having happened), and a send_fn that
raised outright (send_failed, guarded_send's own status name for this
case, reused here so both places call this the same word).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from p1.adapters.factory import get_teams_publisher
from p1.approval.proposals import (
    PENDING,
    IllegalTransitionError,
    Proposal,
    ProposalStore,
)
from p1.approval.write_guard import WriteRefusedError, guarded_send
from p1.config.loader import ChannelConfigStore
from p1.storage.db import DEFAULT_DB_PATH, get_connection
from p1.storage.digests_repo import DigestStore
from p1.storage.escalations_repo import EscalationStore
from p1.storage.nudges_repo import NudgeStore


@dataclass(frozen=True)
class PendingApproval:
    proposal_id: str
    type: str
    channel_id: str
    created_at: str
    summary: str
    payload: dict


@dataclass(frozen=True)
class ActionResult:
    proposal_id: str
    outcome: str  # "sent" | "rejected" | "refused" | "send_failed"
    detail: str


def _summarize(proposal: Proposal) -> PendingApproval:
    payload = proposal.payload
    channel_id = payload.get("channel_id", payload.get("target_channel", "?"))
    if proposal.type == "daily_digest_publish":
        summary = f"First publish for {channel_id} on {payload.get('date', '?')}"
    elif proposal.type == "nudge":
        summary = f"Nudge {payload.get('member_id', '?')} in {channel_id} on {payload.get('date', '?')}"
    elif proposal.type == "escalation":
        summary = (
            f"Escalate {payload.get('member_id', '?')} in {channel_id} "
            f"(streak since {payload.get('streak_start_date', '?')})"
        )
    else:
        summary = f"{proposal.type} proposal for {channel_id}"
    return PendingApproval(
        proposal_id=proposal.id, type=proposal.type, channel_id=channel_id,
        created_at=proposal.created_at, summary=summary, payload=payload,
    )


def _resend_plan(proposal: Proposal, config_store: ChannelConfigStore, publisher, db_path):
    """(action_type, target, send_fn) for a proposal -- the same three
    things the job that created it already passes to guarded_send(),
    read back out of the payload that job itself wrote (never a second,
    independent guess at what it must have meant). escalation is the
    one type whose target is not self-contained in the payload (see
    escalation_job.py's own module docstring): its owner is looked up
    via get_effective_config() so a channel owner changed AFTER the
    escalation was created, but before it was approved, is escalated to
    correctly -- "configuration is really configuration" applies to who
    an approval is even sent to, not only to the non-responder set."""
    payload = proposal.payload
    if proposal.type == "daily_digest_publish":
        target = payload["target_channel"]
        return "channel_post", target, lambda: publisher.post_channel_message(target, payload["content"])
    if proposal.type == "nudge":
        target = payload["member_id"]
        return "nudge", target, lambda: publisher.post_direct_message(target, payload["content"])
    if proposal.type == "escalation":
        owner_id = config_store.get_effective_config(payload["channel_id"], db_path=db_path).channel_owner_id
        return "escalation", owner_id, lambda: publisher.post_direct_message(owner_id, payload["content"])
    raise ValueError(f"Unknown proposal type for resend: {proposal.type!r}")


def _write_audit(db_path, *, actor: str, action: str, entity_id: str, details: dict) -> None:
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO audit (actor, action, entity_type, entity_id, details) VALUES (?, ?, ?, ?, ?)",
            (actor, action, "proposal", entity_id, json.dumps(details)),
        )
        conn.commit()
    finally:
        conn.close()


def list_pending_approvals(
    *, proposal_store: ProposalStore | None = None, db_path: str | Path = DEFAULT_DB_PATH,
) -> list[PendingApproval]:
    """Every proposal awaiting a human decision, oldest first, across
    every capability (nudge/escalation/first-publish) -- the one list
    both surfaces render."""
    proposal_store = proposal_store or ProposalStore(db_path)
    return [_summarize(p) for p in proposal_store.list_by_status(PENDING)]


def approve_and_send(
    proposal_id: str,
    *,
    approver_id: str,
    proposal_store: ProposalStore | None = None,
    config_store: ChannelConfigStore | None = None,
    digest_store: DigestStore | None = None,
    publisher=None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ActionResult:
    """Approve a pending proposal and immediately attempt to send it --
    the one function either surface calls; see this module's own
    docstring for why that is what makes the two surfaces' audit
    records identical rather than merely similar."""
    proposal_store = proposal_store or ProposalStore(db_path)
    config_store = config_store or ChannelConfigStore()
    digest_store = digest_store or DigestStore(db_path)
    publisher = publisher or get_teams_publisher()

    try:
        proposal = proposal_store.approve(proposal_id, approver_id=approver_id)
    except IllegalTransitionError as exc:
        return ActionResult(proposal_id, "refused", str(exc))

    _write_audit(
        db_path, actor=approver_id, action="proposal.approved", entity_id=proposal_id,
        details={"type": proposal.type},
    )

    action_type, target, send_fn = _resend_plan(proposal, config_store, publisher, db_path)
    try:
        guarded_send(
            proposal_id, action_type=action_type, target=target, send_fn=send_fn,
            store=proposal_store, db_path=db_path,
        )
    except WriteRefusedError as exc:
        return ActionResult(proposal_id, "refused", str(exc))
    except Exception as exc:  # noqa: BLE001 -- guarded_send already logged send_failed; report, never raise past this seam
        return ActionResult(proposal_id, "send_failed", f"{type(exc).__name__}: {exc}")

    if proposal.type == "daily_digest_publish":
        # 2026-09-19 finding: run_daily_digest_job() (daily_job.py) only ever
        # calls DigestStore.mark_published() from its OWN success path, at the
        # tail end of the same call that both creates and sends a proposal in
        # one go (the auto-approved-after-first-publish case). A proposal a
        # human approves here, through either real surface, never runs back
        # through that function at all -- so without this call,
        # has_ever_published() would stay False forever for a channel whose
        # publishes are only ever approved by a person, and CHN-17's own
        # documented guarantee ("no channel ever receives an unexpected bot
        # post" applies once, at the first publish, not every day after)
        # would never actually engage. See DECISION_LOG.md.
        digest_store.mark_published(
            idempotency_key=f"{proposal.payload['channel_id']}:{proposal.payload['date']}:daily",
            published_at=datetime.now(timezone.utc).isoformat(),
        )

    # A nudge/escalation a HUMAN approves is sent through this function, not the job
    # that created it -- so the job's own mark_sent() never runs. Without recording
    # the send here, "has this person ever been nudged/escalated?" stays False
    # forever: the spec's "first one needs approval, thereafter unattended" never
    # engages (every later nudge is held again) and escalation, which requires a
    # prior sent nudge, can never fire. Same class of bug as the digest's
    # mark_published() fix above (2026-09-19); found 2026-09-24.
    sent_at = datetime.now(timezone.utc).isoformat()
    if proposal.type == "nudge":
        NudgeStore(db_path).mark_sent(idempotency_key=proposal.idempotency_key, sent_at=sent_at)
    elif proposal.type == "escalation":
        EscalationStore(db_path).mark_sent(idempotency_key=proposal.idempotency_key, sent_at=sent_at)

    return ActionResult(proposal_id, "sent", "sent")


def reject(
    proposal_id: str,
    *,
    approver_id: str,
    proposal_store: ProposalStore | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> ActionResult:
    """Reject a pending proposal -- the one function either surface
    calls. A later send attempt against a rejected proposal is refused
    by guarded_send() the same way it always has been (GC8); this
    function only records the human decision itself."""
    proposal_store = proposal_store or ProposalStore(db_path)
    try:
        proposal = proposal_store.reject(proposal_id, approver_id=approver_id)
    except IllegalTransitionError as exc:
        return ActionResult(proposal_id, "refused", str(exc))

    _write_audit(
        db_path, actor=approver_id, action="proposal.rejected", entity_id=proposal_id,
        details={"type": proposal.type},
    )
    return ActionResult(proposal_id, "rejected", "rejected")
