"""
CHN-25's own acceptance test, executed rather than merely asserted:
"Approving from Teams and from the fallback surface produce identical
audit records - proving the gate lives in the service, not the UI."

Every test here creates two equivalent proposals/config changes, drives
one through p1.adapters.copilot_studio_connector (standing in for
Teams/Copilot Studio) and the other through p1.approval.service /
p1.config.loader.ChannelConfigStore directly (standing in for the
Streamlit fallback -- app/approval_dashboard.py calls these same
functions with these same keyword arguments, see
test_approval_dashboard_app.py for that surface driven directly), then
diffs the resulting write_log/audit rows' STRUCTURE -- same columns
populated, same status/action_type values -- never their proposal-
specific values (ids, timestamps, message content necessarily differ
between two different proposals).

The last two tests check the adaptive card templates themselves never
drift from the connector's actual request contract -- each card's
Action.Submit `data` keys (minus the runtime-supplied ${...}
placeholders) must be a subset of what its handler actually accepts,
checked programmatically rather than by hand, the same "docs cannot
outrun the code" discipline D10 asks for at the whole-repo level,
applied here at the row that introduces this doc.
"""

from __future__ import annotations

import json
from pathlib import Path

from p1.adapters import copilot_studio_connector as connector
from p1.approval import service
from p1.approval.proposals import ProposalStore
from p1.config.loader import ChannelConfigStore
from p1.storage.db import get_connection, init_db

CHANNEL_ID = "cx-channel"
CARDS_DIR = Path(__file__).resolve().parents[2] / "src" / "p1" / "adapters" / "copilot_studio_cards"


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def post_direct_message(self, member_id: str, content: str) -> dict:
        self.calls.append(("dm", member_id, content))
        return {"ok": True}

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        self.calls.append(("channel", channel_id, content))
        return {"ok": True}


def _seed_db(db_path) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'Cx Channel', 1)", (CHANNEL_ID,))
        for member_id in ("alice", "bob", "priya"):
            conn.execute("INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()


def _write_log_row(db_path, proposal_id: str):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT action_type, target, status FROM write_log WHERE proposal_id = ? AND status = 'sent'",
            (proposal_id,),
        ).fetchone()
    finally:
        conn.close()


def _audit_row(db_path, entity_id: str, action: str):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT actor, action, entity_type FROM audit WHERE entity_id = ? AND action = ?",
            (entity_id, action),
        ).fetchone()
    finally:
        conn.close()


def test_approving_via_the_connector_and_via_the_service_directly_produce_the_same_shape_of_audit_record(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    store = ProposalStore(db_path)

    connector_proposal = store.create(
        type="nudge", payload={"channel_id": CHANNEL_ID, "member_id": "alice", "date": "2026-06-01", "content": "hi alice"},
        original_model_output={}, source_refs=[], idempotency_key="via-connector",
    )
    direct_proposal = store.create(
        type="nudge", payload={"channel_id": CHANNEL_ID, "member_id": "bob", "date": "2026-06-01", "content": "hi bob"},
        original_model_output={}, source_refs=[], idempotency_key="via-streamlit",
    )

    publisher_a, publisher_b = _RecordingPublisher(), _RecordingPublisher()

    # "Teams" path: the connector's own handler, the thing a Copilot
    # Studio custom connector action would actually call.
    connector_response = connector.handle_approve(
        {"proposal_id": connector_proposal.id, "approver_id": "priya"},
        publisher=publisher_a, db_path=db_path,
    )
    # "Fallback" path: app/approval_dashboard.py's own call shape.
    service.approve_and_send(direct_proposal.id, approver_id="priya", publisher=publisher_b, db_path=db_path)

    assert connector_response["outcome"] == "sent"

    row_a = _write_log_row(db_path, connector_proposal.id)
    row_b = _write_log_row(db_path, direct_proposal.id)
    assert row_a is not None and row_b is not None
    assert (row_a["action_type"], row_a["status"]) == (row_b["action_type"], row_b["status"]) == ("nudge", "sent")

    audit_a = _audit_row(db_path, connector_proposal.id, "proposal.approved")
    audit_b = _audit_row(db_path, direct_proposal.id, "proposal.approved")
    assert audit_a is not None and audit_b is not None
    assert (audit_a["actor"], audit_a["entity_type"]) == (audit_b["actor"], audit_b["entity_type"]) == ("priya", "proposal")


def test_rejecting_via_the_connector_and_via_the_service_directly_produce_the_same_shape_of_audit_record(tmp_path):
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    store = ProposalStore(db_path)

    p_connector = store.create(
        type="escalation", payload={"channel_id": CHANNEL_ID, "member_id": "alice", "content": "x"},
        original_model_output={}, source_refs=[], idempotency_key="reject-via-connector",
    )
    p_direct = store.create(
        type="escalation", payload={"channel_id": CHANNEL_ID, "member_id": "bob", "content": "y"},
        original_model_output={}, source_refs=[], idempotency_key="reject-via-streamlit",
    )

    connector.handle_reject({"proposal_id": p_connector.id, "approver_id": "priya"}, db_path=db_path)
    service.reject(p_direct.id, approver_id="priya", db_path=db_path)

    audit_a = _audit_row(db_path, p_connector.id, "proposal.rejected")
    audit_b = _audit_row(db_path, p_direct.id, "proposal.rejected")
    assert audit_a is not None and audit_b is not None
    assert dict(audit_a) == dict(audit_b) | {"entity_type": audit_a["entity_type"]}  # same shape, both "proposal"/"priya"
    assert audit_a["actor"] == audit_b["actor"] == "priya"
    assert audit_a["entity_type"] == audit_b["entity_type"] == "proposal"


def test_updating_config_via_the_connector_and_via_the_store_directly_produce_the_same_shape_of_audit_record(tmp_path):
    import yaml

    db_path = tmp_path / "test.db"
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    data = {
        "channel_id": CHANNEL_ID, "display_name": "Cx Channel", "allowlisted": True,
        "roster": ["alice", "bob"], "update_window_start": "09:00:00", "update_window_end": "11:00:00",
        "timezone": "UTC", "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "daily_digest_time": "09:00:00", "weekly_digest_day": "Fri", "weekly_digest_time": "16:00:00",
        "channel_owner_id": "priya",
    }
    (config_dir / f"{CHANNEL_ID}.yaml").write_text(yaml.safe_dump(data))
    init_db(db_path)
    ChannelConfigStore(config_dir).sync_to_db(db_path=db_path)

    # "Teams" path: the card can only submit flat text -- exercise the
    # _csv translation the connector's handler does for real.
    connector_response = connector.handle_update_channel_config(
        {"channel_id": CHANNEL_ID, "updated_by": "priya", "roster_csv": "alice,carol"}, db_path=db_path,
    )
    assert connector_response["roster"] == ["alice", "carol"]

    audit = _audit_row(db_path, CHANNEL_ID, "channel_config.updated")
    assert audit is not None
    assert audit["actor"] == "priya"

    # "Fallback" path: the Streamlit form's own richer widgets submit a
    # real list directly -- same underlying call, same audit shape.
    direct = ChannelConfigStore(config_dir).update_channel_config(
        CHANNEL_ID, roster=["alice", "bob", "dave"], updated_by="priya", db_path=db_path,
    )
    assert direct.roster == ["alice", "bob", "dave"]
    conn = get_connection(db_path)
    try:
        audit_count = conn.execute(
            "SELECT COUNT(*) AS n FROM audit WHERE entity_id = ? AND action = 'channel_config.updated'", (CHANNEL_ID,)
        ).fetchone()["n"]
    finally:
        conn.close()
    assert audit_count == 2  # one per path, same shape each time


def _card_submit_keys(card_path: Path) -> list[set[str]]:
    """Every Action.Submit's `data` keys in a card, with runtime-
    supplied ${...} placeholders' VALUES ignored -- only the keys
    matter for checking against a handler's request shape."""
    card = json.loads(card_path.read_text())
    return [set(action["data"].keys()) for action in card.get("actions", []) if action.get("type") == "Action.Submit"]


def test_pending_action_cards_submit_exactly_what_handle_approve_and_handle_reject_expect():
    expected = {"action", "proposal_id", "approver_id"}
    for name in ("pending_nudge_card.json", "pending_escalation_card.json", "pending_publish_card.json"):
        for submit_keys in _card_submit_keys(CARDS_DIR / name):
            assert submit_keys == expected, f"{name} submits {submit_keys}, handlers expect {expected}"


def test_config_form_card_submits_only_what_handle_update_channel_config_accepts():
    accepted = {"action", "channel_id", "updated_by", "roster_csv", "update_window_start", "update_window_end", "exceptions_csv"}
    for submit_keys in _card_submit_keys(CARDS_DIR / "channel_config_form_card.json"):
        assert submit_keys.issubset(accepted), submit_keys - accepted
        assert {"channel_id", "updated_by"}.issubset(submit_keys)
