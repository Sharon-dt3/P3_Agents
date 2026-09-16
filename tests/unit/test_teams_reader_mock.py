import pytest

from p1.adapters.factory import get_teams_reader
from p1.adapters.teams_reader import TeamsChannel, TeamsMember, TeamsMessage
from p1.adapters.teams_reader_mock import MockTeamsReader
from p1.governance.scope_gate import ScopedTeamsReader


def _reader():
    channels = [TeamsChannel(id="c1", display_name="Channel One")]
    members = {"c1": [TeamsMember(id="u1", display_name="User One")]}
    messages = {
        "c1": [
            TeamsMessage(id="m1", channel_id="c1", author_id="u1", posted_at="2026-09-01T09:00:00Z", body="first"),
            TeamsMessage(id="m2", channel_id="c1", author_id="u1", thread_root_id="m1", posted_at="2026-09-01T09:05:00Z", body="reply"),
        ]
    }
    return MockTeamsReader(channels, members, messages)


def test_list_channels_and_members():
    reader = _reader()
    assert [c.id for c in reader.list_channels()] == ["c1"]
    assert [m.id for m in reader.list_channel_members("c1")] == ["u1"]


def test_list_messages_full_then_incremental_delta():
    reader = _reader()
    page1 = reader.list_messages("c1")
    assert len(page1.messages) == 2

    page2 = reader.list_messages("c1", delta_token=page1.delta_token)
    assert page2.messages == []


def test_list_replies_finds_thread_children():
    reader = _reader()
    replies = reader.list_replies("m1")
    assert [r.id for r in replies] == ["m2"]


def test_get_permalink_unknown_message_raises():
    reader = _reader()
    with pytest.raises(KeyError):
        reader.get_permalink("does-not-exist")


def test_from_fixtures_loads_committed_seed_data():
    reader = MockTeamsReader.from_fixtures()
    channel_ids = {c.id for c in reader.list_channels()}
    assert "19:proj-alpha@thread.tacv2" in channel_ids


def test_factory_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("TEAMS_READER_MODE", raising=False)
    reader = get_teams_reader()
    assert isinstance(reader, ScopedTeamsReader)
    assert isinstance(reader.wrapped_reader, MockTeamsReader)


def test_factory_selects_graph_by_config(monkeypatch):
    monkeypatch.setenv("TEAMS_READER_MODE", "graph")
    monkeypatch.setenv("GRAPH_ACCESS_TOKEN", "fake-token")
    monkeypatch.setenv("GRAPH_TEAM_ID", "fake-team")

    reader = get_teams_reader()

    from p1.adapters.teams_reader_graph import GraphTeamsReader
    assert isinstance(reader, ScopedTeamsReader)
    assert isinstance(reader.wrapped_reader, GraphTeamsReader)
