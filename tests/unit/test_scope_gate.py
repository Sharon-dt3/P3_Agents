import json

import pytest

from p1.adapters.teams_reader import MessagePage, TeamsChannel, TeamsMessage
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


def test_note_known_message_lets_a_previously_unseen_message_id_through_for_an_allowlisted_channel(db_path):
    # Simulates the real case this method exists for: a fresh gate
    # instance (a new process tick) that never itself called
    # list_messages()/list_replies() for "m1", re-asserting it as
    # already-known, already-allowlisted data (e.g. read back from
    # `messages`) rather than fetching it again.
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    gate.note_known_message("m1", "allowed-1")
    assert gate.list_replies("m1") == []
    gate.get_permalink("m1")  # does not raise


def test_note_known_message_still_refuses_a_non_allowlisted_channel(db_path):
    # The whole point: this method must never be usable to smuggle an
    # out-of-scope channel_id past the allowlist -- it still runs
    # through _enforce() exactly like every other operation here.
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.note_known_message("m2", "not-allowed-1")
    # And since the enforce failed, "m2" must never have been recorded
    # as known either -- list_replies must still refuse it too.
    with pytest.raises(ScopeViolationError):
        gate.list_replies("m2")


def test_note_known_message_refusal_is_recorded_in_the_audit_table(db_path):
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    with pytest.raises(ScopeViolationError):
        gate.note_known_message("m2", "not-allowed-1")

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
    assert details["operation"] == "note_known_message"


class _ReaderWithNoteKnownMessage:
    """A minimal fake reader exposing note_known_message(), to prove
    ScopedTeamsReader.note_known_message() forwards to it when present.
    The real case this stands in for is GraphTeamsReader's own separate
    message_id->channel_id cache (see teams_reader_graph.py's own
    docstring and this fix's 2026-09-21 DECISION_LOG.md entry) -- but
    nothing here needs a real Graph reader to prove the forwarding
    itself happens, just something that duck-types the same method."""

    def __init__(self):
        self.noted: list[tuple[str, str]] = []

    def list_channels(self):
        return [TeamsChannel(id="allowed-1", display_name="Allowed Channel")]

    def list_channel_members(self, channel_id):
        return []

    def list_messages(self, channel_id, since=None, delta_token=None):
        return MessagePage(messages=[], delta_token="", has_more=False)

    def list_replies(self, message_id):
        return []

    def get_permalink(self, message_id):
        return ""

    def note_known_message(self, message_id, channel_id):
        self.noted.append((message_id, channel_id))


def test_note_known_message_forwards_to_a_wrapped_reader_that_also_exposes_it(db_path):
    # 2026-09-21 live finding: seeding only the gate's own cache was not
    # enough -- GraphTeamsReader keeps an entirely separate cache that
    # list_replies() actually resolves channel_id from once the call is
    # delegated to the wrapped reader, so without this forwarding a
    # message the gate now considers known still made the wrapped
    # reader's own list_replies() raise KeyError. See DECISION_LOG.md.
    wrapped = _ReaderWithNoteKnownMessage()
    gate = ScopedTeamsReader(wrapped, allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    gate.note_known_message("m1", "allowed-1")
    assert wrapped.noted == [("m1", "allowed-1")]


def test_note_known_message_does_not_forward_to_a_wrapped_reader_without_it(db_path):
    # MockTeamsReader has no note_known_message -- it doesn't need one,
    # since its own list_replies() scans every channel's messages
    # directly rather than resolving via a cache. Must not raise.
    gate = ScopedTeamsReader(_reader(), allowlisted_channel_ids=["allowed-1"], db_path=db_path)
    gate.note_known_message("m1", "allowed-1")  # does not raise
