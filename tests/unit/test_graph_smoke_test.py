"""
Proves scripts/graph_smoke_test.py's read-only live-connection check --
listing channels, filtering to this repo's own allowlist, and previewing
one page of messages -- without ever opening a real Graph connection.
Every test injects a fake reader via run_smoke_test's reader_factory
seam.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import graph_smoke_test

from p1.adapters.teams_reader import MessagePage, TeamsChannel, TeamsMessage

ALLOWLISTED_CHANNEL_ID = "19:proj-alpha@thread.tacv2"  # config/channels/proj-alpha.yaml
NOT_ALLOWLISTED_CHANNEL_ID = "19:some-other-real-channel@thread.tacv2"


class _FakeGraphReader:
    def __init__(self, access_token, team_id, channels=None, messages=None):
        self.access_token = access_token
        self.team_id = team_id
        self._channels = channels or []
        self._messages = messages or []
        self.messages_requested_for = None

    def list_channels(self):
        return self._channels

    def list_messages(self, channel_id):
        self.messages_requested_for = channel_id
        return MessagePage(messages=self._messages, delta_token="tok-1", has_more=False)


def test_run_smoke_test_reports_zero_channels(capsys):
    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok",
        team_id="team-1",
        reader_factory=lambda access_token, team_id: _FakeGraphReader(access_token, team_id, channels=[]),
    )
    assert exit_code == 0
    assert "zero channels" in capsys.readouterr().out


def test_run_smoke_test_names_channels_not_on_the_allowlist_but_does_not_read_them(capsys):
    fake = _FakeGraphReader(
        "tok",
        "team-1",
        channels=[TeamsChannel(id=NOT_ALLOWLISTED_CHANNEL_ID, display_name="Some Other Channel")],
    )

    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok", team_id="team-1", reader_factory=lambda access_token, team_id: fake,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert NOT_ALLOWLISTED_CHANNEL_ID in out
    assert "are on this repo's allowlist yet" in out
    assert fake.messages_requested_for is None  # never read -- scope gate discipline


def test_run_smoke_test_reads_one_page_from_an_allowlisted_channel(capsys):
    fake = _FakeGraphReader(
        "tok",
        "team-1",
        channels=[
            TeamsChannel(id=NOT_ALLOWLISTED_CHANNEL_ID, display_name="Some Other Channel"),
            TeamsChannel(id=ALLOWLISTED_CHANNEL_ID, display_name="Project Alpha"),
        ],
        messages=[
            TeamsMessage(
                id="m1",
                channel_id=ALLOWLISTED_CHANNEL_ID,
                author_id="priya.sharma",
                posted_at="2025-06-05T09:15:00Z",
            )
        ],
    )

    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok", team_id="team-1", reader_factory=lambda access_token, team_id: fake,
    )

    assert exit_code == 0
    assert fake.messages_requested_for == ALLOWLISTED_CHANNEL_ID
    out = capsys.readouterr().out
    assert "priya.sharma" in out
    assert "2025-06-05T09:15:00Z" in out
    assert "Live Graph connection confirmed" in out


def test_run_smoke_test_reports_connected_but_empty_channel(capsys):
    fake = _FakeGraphReader(
        "tok",
        "team-1",
        channels=[TeamsChannel(id=ALLOWLISTED_CHANNEL_ID, display_name="Project Alpha")],
        messages=[],
    )

    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok", team_id="team-1", reader_factory=lambda access_token, team_id: fake,
    )

    assert exit_code == 0
    assert "zero messages returned" in capsys.readouterr().out


def test_main_fails_cleanly_when_graph_env_vars_missing(monkeypatch, capsys):
    monkeypatch.delenv("GRAPH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("GRAPH_TEAM_ID", raising=False)

    exit_code = graph_smoke_test.main()

    assert exit_code == 1
    assert "GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID" in capsys.readouterr().out


def test_main_delegates_to_run_smoke_test_with_env_values(monkeypatch):
    monkeypatch.setenv("GRAPH_ACCESS_TOKEN", "tok-from-env")
    monkeypatch.setenv("GRAPH_TEAM_ID", "team-from-env")
    seen = {}

    def fake_run_smoke_test(*, access_token, team_id):
        seen["access_token"] = access_token
        seen["team_id"] = team_id
        return 0

    monkeypatch.setattr(graph_smoke_test, "run_smoke_test", fake_run_smoke_test)

    exit_code = graph_smoke_test.main()

    assert exit_code == 0
    assert seen == {"access_token": "tok-from-env", "team_id": "team-from-env"}
