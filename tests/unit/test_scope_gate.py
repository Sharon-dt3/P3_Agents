import json

import pytest

from p1.adapters.teams_reader import TeamsChannel, TeamsMessage
from p1.adapters.teams_reader_mock import MockTeamsReader
from p1.governance.scope_gate import ScopedTeamsReader, ScopeViolationError
from p1.storage.db import get_connection, init_db


def _reader():
    channels = [
        TeamsChannel(id="allowed-1", display_name="Allowed Channel"),
        TeamsChannel(id="not-allowed-1", display_name="Not Allowed Channel"),
    ]
    members = {"allowed-1": [], "not-allowed-1": []}
    messages = {
        "allowed-1": [
            TeamsMessage(id="m1", channel_id="allowed-1", author_id="u1", posted_at="2026-09-01T09:00:00Z", body="hi"),
        ],
        "not-allowed-1": [
            TeamsMessage(id="m2", channel_id="not-allowed-1", author_id="u2", posted_at="2026-09-01T09:00:00Z", body="secret"),
        ],
    }
    return MockTeamsReader(channels, members, messages)


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


def test_list_channels_filters_to_allowlist_only(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    assert [c.id for c in gate.list_channels()] == ["allowed-1"]


def test_list_messages_on_allowlisted_channel_succeeds(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    page = gate.list_messages("allowed-1")
    assert [m.id for m in page.messages] == ["m1"]


def test_list_messages_on_non_allowlisted_channel_raises(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.list_messages("not-allowed-1")


def test_list_messages_on_a_chat_id_raises_the_same_way(db_path):
    # A chat ID was never on the channel allowlist in the first place --
    # the same check that blocks an unlisted channel structurally blocks
    # any chat too, with no separate "is this a chat" logic needed.
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.list_messages("19:some-group-chat@unq.gbl.spaces")


def test_list_channel_members_on_allowlisted_channel_succeeds(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    assert gate.list_channel_members("allowed-1") == []


def test_list_channel_members_on_non_allowlisted_channel_raises(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.list_channel_members("not-allowed-1")


def test_refusal_is_recorded_in_the_audit_table(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.list_messages("not-allowed-1")

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT actor, action, entity_type, entity_id, details FROM audit"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    actor, action, entity_type, entity_id, details_json = row
    assert actor == "scope_gate"
    assert action == "refuse_read"
    assert entity_type == "channel"
    assert entity_id == "not-allowed-1"
    details = json.loads(details_json)
    assert details["operation"] == "list_messages"


def test_list_replies_for_a_message_never_seen_via_a_gated_call_raises(db_path):
    # No list_messages() call happened first -- this gate has no record
    # of "m1" belonging to any channel, and must refuse rather than pass
    # it straight through to the wrapped reader (2026-09-20 fix: this
    # used to pass through unconditionally -- see scope_gate.py's own
    # docstring and DECISION_LOG.md).
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.list_replies("m1")


def test_get_permalink_for_a_message_never_seen_via_a_gated_call_raises(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.get_permalink("m1")


def test_list_replies_and_get_permalink_succeed_once_the_message_was_returned_by_a_gated_call(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    gate.list_messages("allowed-1")  # "m1" is now legitimately known to this gate
    assert gate.list_replies("m1") == []
    gate.get_permalink("m1")  # does not raise


def test_list_replies_still_refuses_an_out_of_scope_message_even_though_the_wrapped_reader_would_answer_it(db_path):
    # MockTeamsReader.list_replies()/get_permalink() scan across every
    # channel's messages, not just allowlisted ones -- this proves "m2"
    # is refused because THIS gate never legitimately saw it (its own
    # channel, "not-allowed-1", was never listed through the gate), not
    # merely because the wrapped reader happens to also refuse it.
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.list_replies("m2")
    with pytest.raises(ScopeViolationError):
        gate.get_permalink("m2")


def test_refusal_of_an_unseen_message_id_is_recorded_in_the_audit_table(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.list_replies("m1")

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT actor, action, entity_type, entity_id, details FROM audit"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    actor, action, entity_type, entity_id, details_json = row
    assert actor == "scope_gate"
    assert action == "refuse_read"
    assert entity_type == "message"
    assert entity_id == "m1"
    details = json.loads(details_json)
    assert details["operation"] == "list_replies"
