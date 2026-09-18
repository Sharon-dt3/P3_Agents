"""
CHN-25: the Copilot Studio custom connector's backend handlers (P1 Channel).

Copilot Studio and Dataverse are Microsoft low-code surfaces that live
in a tenant's own portal, not as importable Python -- there is no live
Microsoft tenant this repo can build or exercise them against, exactly
the same constraint CHN-22 already worked around for Power Automate
(a real adapter class, implementing the real contract, never exercised
against a live flow). What CAN be built and proven here is the thing
that actually matters for this row's own acceptance test: the exact
backend contract a Copilot Studio custom connector's actions would call
-- implemented for real, tested by calling it directly with the same
JSON-shaped request a connector action would send, never exercised
against a live Copilot Studio bot or Dataverse table. See
docs/copilot_studio/connector_contract.md for the request/response
schema each handler below implements, and
docs/copilot_studio/cards/*.json for the adaptive cards whose
Action.Submit `data` is exactly a handle_approve/handle_reject/
handle_update_channel_config request.

Every handler here does exactly one thing: adapt a JSON request/
response shape to a call into p1.approval.service or
p1.config.loader.ChannelConfigStore -- the SAME functions
app/approval_dashboard.py's Streamlit fallback calls directly, with the
same keyword arguments. There is no branch anywhere in this module, or
in the functions it calls, that behaves differently depending on which
of the two ever calls it -- see
tests/unit/test_copilot_studio_connector.py for the equivalence proof.

approver_id/updated_by are passed explicitly by every caller here (test
or otherwise). In a real deployment, Copilot Studio would supply this
from the Teams user's own identity (its built-in User.Id/DisplayName
context, never a value the card's own submitted JSON could spoof) --
not represented here since there is no live Teams/Entra identity to
bind to.

db_path/proposal_store/config_store/publisher are test-only seams
(every other job/service function in this codebase takes them the same
way) -- never part of the actual connector's wire contract, which is
just the request dict documented per handler and in
connector_contract.md.
"""

from __future__ import annotations

from datetime import time as time_type
from pathlib import Path

from p1.approval import service as approval_service
from p1.config.loader import ChannelConfigStore
from p1.config.schema import ExceptionEntry
from p1.storage.db import DEFAULT_DB_PATH


def handle_list_pending_approvals(
    request: dict, *, db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """request: {} -- no fields required."""
    approvals = approval_service.list_pending_approvals(db_path=db_path)
    return {
        "approvals": [
            {
                "proposal_id": a.proposal_id,
                "type": a.type,
                "channel_id": a.channel_id,
                "created_at": a.created_at,
                "summary": a.summary,
            }
            for a in approvals
        ]
    }


def handle_approve(
    request: dict,
    *,
    publisher=None,
    config_store: ChannelConfigStore | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict:
    """request: {"proposal_id": str, "approver_id": str}."""
    result = approval_service.approve_and_send(
        request["proposal_id"], approver_id=request["approver_id"],
        publisher=publisher, config_store=config_store, db_path=db_path,
    )
    return {"proposal_id": result.proposal_id, "outcome": result.outcome, "detail": result.detail}


def handle_reject(request: dict, *, db_path: str | Path = DEFAULT_DB_PATH) -> dict:
    """request: {"proposal_id": str, "approver_id": str}."""
    result = approval_service.reject(request["proposal_id"], approver_id=request["approver_id"], db_path=db_path)
    return {"proposal_id": result.proposal_id, "outcome": result.outcome, "detail": result.detail}


def _parse_roster_csv(roster_csv: str) -> list[str]:
    return [m.strip() for m in roster_csv.split(",") if m.strip()]


def _parse_exceptions_csv(exceptions_csv: str) -> list[dict]:
    """"member_id:reason,member_id:reason" -- channel_config_form_card.json's
    Input.Text fields cannot submit a JSON array (Adaptive Cards has no
    list-input control), so this is the one place that flat text is
    turned back into the same shape ChannelConfigStore.update_channel_config()
    already validates via ExceptionEntry -- never a second, looser
    validation of its own."""
    entries = []
    for chunk in exceptions_csv.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        member_id, _, reason = chunk.partition(":")
        entries.append({"member_id": member_id.strip(), "reason": reason.strip()})
    return entries


def handle_update_channel_config(request: dict, *, db_path: str | Path = DEFAULT_DB_PATH) -> dict:
    """request: {"channel_id": str, "updated_by": str}, plus any of:
    "roster" (list[str]) or "roster_csv" (str, as
    channel_config_form_card.json's Input.Text submits it);
    "update_window_start"/"update_window_end" ("HH:MM:SS");
    "exceptions" (list of {"member_id", "reason"}) or "exceptions_csv"
    (str, "member_id:reason,member_id:reason", as the card submits it).
    Fields left out are left unchanged -- see
    ChannelConfigStore.update_channel_config()'s own docstring. The
    _csv variants exist only because Adaptive Cards has no list-input
    control; the Streamlit fallback's own widgets submit "roster"/
    "exceptions" directly, and both paths call
    update_channel_config() with the exact same resulting kwargs."""
    kwargs: dict = {"updated_by": request["updated_by"], "db_path": db_path}
    if "roster" in request:
        kwargs["roster"] = request["roster"]
    elif "roster_csv" in request:
        kwargs["roster"] = _parse_roster_csv(request["roster_csv"])
    if "update_window_start" in request:
        kwargs["update_window_start"] = time_type.fromisoformat(request["update_window_start"])
    if "update_window_end" in request:
        kwargs["update_window_end"] = time_type.fromisoformat(request["update_window_end"])
    if "exceptions" in request:
        kwargs["exceptions"] = [ExceptionEntry.model_validate(e) for e in request["exceptions"]]
    elif "exceptions_csv" in request:
        kwargs["exceptions"] = [ExceptionEntry.model_validate(e) for e in _parse_exceptions_csv(request["exceptions_csv"])]

    new_config = ChannelConfigStore().update_channel_config(request["channel_id"], **kwargs)
    return {
        "channel_id": new_config.channel_id,
        "roster": new_config.roster,
        "update_window_start": new_config.update_window_start.isoformat(),
        "update_window_end": new_config.update_window_end.isoformat(),
        "exceptions": [e.model_dump() for e in new_config.exceptions],
        "version": new_config.version,
    }
