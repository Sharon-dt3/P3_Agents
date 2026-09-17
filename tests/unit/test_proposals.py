"""
SPN-08's own acceptance test: "An edited-then-approved proposal retains
both the original model output and the applied payload." Also covers
the status machine's legal/illegal transitions, idempotent create, and
that nothing here assumes a P1-specific shape -- SPN-08 is meant to be
"reused verbatim by P2 and P3."
"""

from __future__ import annotations

import pytest

from p1.approval.proposals import (
    APPLIED,
    APPROVED,
    PENDING,
    REJECTED,
    IllegalTransitionError,
    ProposalNotFoundError,
    ProposalStore,
)
from p1.storage.db import init_db


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


@pytest.fixture
def store(db_path):
    return ProposalStore(db_path)


def _create(store, **overrides):
    defaults = {
        "type": "daily_digest",
        "payload": {"content": "draft content"},
        "original_model_output": {"content": "draft content"},
        "source_refs": ["msg-1", "msg-2"],
        "idempotency_key": "chan-1:2026-06-01:daily",
    }
    defaults.update(overrides)
    return store.create(**defaults)


# --- create -----------------------------------------------------------


def test_create_returns_a_pending_proposal_with_the_given_fields(store):
    proposal = _create(store)
    assert proposal.status == PENDING
    assert proposal.type == "daily_digest"
    assert proposal.payload == {"content": "draft content"}
    assert proposal.original_model_output == {"content": "draft content"}
    assert proposal.source_refs == ("msg-1", "msg-2")
    assert proposal.approver_id is None
    assert proposal.decided_at is None
    assert proposal.idempotency_key == "chan-1:2026-06-01:daily"


def test_create_is_idempotent_on_the_idempotency_key(store):
    first = _create(store)
    second = _create(store, payload={"content": "a completely different draft"})
    assert first.id == second.id
    assert second.payload == {"content": "draft content"}  # the second call's payload was ignored


def test_create_does_not_reset_an_already_decided_proposal(store):
    """The important difference from DigestStore's own upsert-on-key: a
    retried create() for a proposal that has already been decided must
    never silently reset it back to pending, or an approval could be
    wiped out by nothing more than the same digest job running twice."""
    proposal = _create(store)
    store.approve(proposal.id, approver_id="priya", payload={"content": "approved version"})

    retried = _create(store, payload={"content": "yet another draft"})

    assert retried.status == APPROVED
    assert retried.payload == {"content": "approved version"}


def test_get_by_idempotency_key_returns_none_when_absent(store):
    assert store.get_by_idempotency_key("no-such-key") is None


def test_get_raises_for_an_unknown_id(store):
    with pytest.raises(ProposalNotFoundError):
        store.get("does-not-exist")


# --- SPN-08's own acceptance test ---------------------------------------


def test_an_edited_then_approved_proposal_retains_both_the_original_and_the_applied_payload(store):
    proposal = _create(
        store,
        original_model_output={"content": "Alice shipped the export job. Bob has no updates."},
    )

    approved = store.approve(
        proposal.id,
        approver_id="priya",
        payload={"content": "Alice shipped the export job."},  # human dropped the false claim about Bob
    )
    assert approved.status == APPROVED
    assert approved.original_model_output == {"content": "Alice shipped the export job. Bob has no updates."}
    assert approved.payload == {"content": "Alice shipped the export job."}

    applied = store.apply(approved.id)
    assert applied.status == APPLIED
    # Both readable independently, after the full lifecycle to applied --
    # the model's original draft is never overwritten by the edit, and
    # the edit is never lost once applied.
    assert applied.original_model_output == {"content": "Alice shipped the export job. Bob has no updates."}
    assert applied.payload == {"content": "Alice shipped the export job."}
    assert applied.approver_id == "priya"
    assert applied.decided_at == approved.decided_at  # apply() is not a second decision


def test_approve_with_no_payload_override_keeps_the_original_model_output_as_the_payload(store):
    proposal = _create(store)
    approved = store.approve(proposal.id, approver_id="priya")
    assert approved.payload == proposal.original_model_output


# --- reject -------------------------------------------------------------


def test_reject_sets_status_approver_and_decided_at(store):
    proposal = _create(store)
    rejected = store.reject(proposal.id, approver_id="priya")
    assert rejected.status == REJECTED
    assert rejected.approver_id == "priya"
    assert rejected.decided_at is not None
    assert rejected.payload == proposal.payload  # rejecting never edits anything


# --- illegal transitions -------------------------------------------------


def test_approving_an_already_approved_proposal_raises(store):
    proposal = _create(store)
    store.approve(proposal.id, approver_id="priya")
    with pytest.raises(IllegalTransitionError):
        store.approve(proposal.id, approver_id="priya")


def test_approving_a_rejected_proposal_raises(store):
    proposal = _create(store)
    store.reject(proposal.id, approver_id="priya")
    with pytest.raises(IllegalTransitionError):
        store.approve(proposal.id, approver_id="priya")


def test_rejecting_an_applied_proposal_raises(store):
    proposal = _create(store)
    store.approve(proposal.id, approver_id="priya")
    store.apply(proposal.id)
    with pytest.raises(IllegalTransitionError):
        store.reject(proposal.id, approver_id="priya")


def test_applying_a_still_pending_proposal_raises(store):
    proposal = _create(store)
    with pytest.raises(IllegalTransitionError):
        store.apply(proposal.id)


def test_applying_an_already_applied_proposal_raises(store):
    proposal = _create(store)
    store.approve(proposal.id, approver_id="priya")
    store.apply(proposal.id)
    with pytest.raises(IllegalTransitionError):
        store.apply(proposal.id)


def test_illegal_transition_error_names_the_legal_destinations(store):
    proposal = _create(store)
    store.approve(proposal.id, approver_id="priya")
    with pytest.raises(IllegalTransitionError, match="applied"):
        store.reject(proposal.id, approver_id="priya")


# --- reused verbatim by P2/P3: no P1-specific assumption anywhere --------


@pytest.mark.parametrize(
    "proposal_type,payload",
    [
        ("daily_digest", {"channel_id": "c1", "date": "2026-06-01", "content": "..."}),
        ("tracker_update", {"tracker": "jira", "ticket": "PROJ-42", "field": "status", "value": "Done"}),
        ("backlog_item", {"title": "Add rate limiting", "epic": "reliability"}),
    ],
)
def test_store_makes_no_assumption_about_type_or_payload_shape(store, proposal_type, payload):
    proposal = store.create(
        type=proposal_type,
        payload=payload,
        original_model_output=payload,
        source_refs=["ref-1"],
        idempotency_key=f"{proposal_type}:key",
    )
    approved = store.approve(proposal.id, approver_id="someone")
    assert approved.type == proposal_type
    assert approved.payload == payload


def test_source_refs_round_trip_as_an_ordered_tuple(store):
    proposal = _create(store, source_refs=["msg-3", "msg-1", "msg-2"])
    assert proposal.source_refs == ("msg-3", "msg-1", "msg-2")
