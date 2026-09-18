"""
Proves scripts/graph_smoke_test.py's read-only live-connection check --
reading the channel(s) to test from this repo's own allowlist
(config/channels/*.yaml) rather than asking Graph to enumerate them,
then previewing one page of messages per allowlisted channel_id --
without ever opening a real Graph connection or depending on this
repo's actual committed channel configs. Every test injects a fake
reader via run_smoke_test's reader_factory seam and a temp-dir-backed
ChannelConfigStore via its config_store seam.

See DECISION_LOG.md's CHN-01 follow-up for why this script stopped
calling Graph's list_channels() (it needs Channel.ReadBasic.All, a
second admin-consent grant beyond ChannelMessage.Read.All) in favor of
reading the allowlist straight from config, which already knows which
channel_ids are in scope.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import graph_smoke_test

from p1.adapters.teams_reader import MessagePage, TeamsMessage
from p1.config.loader import ChannelConfigStore

ALLOWLISTED_CHANNEL_ID = "19:proj-alpha@thread.tacv2"
SECOND_ALLOWLISTED_CHANNEL_ID = "19:p1-agent-test@thread.tacv2"

_BASE_CONFIG = {
    "display_name": "Test Channel",
    "allowlisted": True,
    "roster": ["priya.sharma"],
    "update_window_start": "09:00:00",
    "update_window_end": "11:00:00",
    "timezone": "Asia/Colombo",
    "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "daily_digest_time": "11:30:00",
    "weekly_digest_day": "Fri",
    "weekly_digest_time": "16:00:00",
    "channel_owner_id": "priya.sharma",
}


def _write_config(config_dir: Path, channel_id: str, **overrides) -> None:
    data = dict(_BASE_CONFIG, channel_id=channel_id, **overrides)
    (config_dir / f"{channel_id.replace(':', '_').replace('@', '_')}.yaml").write_text(yaml.safe_dump(data))


def _config_store(tmp_path: Path) -> ChannelConfigStore:
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    return ChannelConfigStore(config_dir)


class _FakeGraphReader:
    def __init__(self, access_token, team_id, messages_by_channel=None, error_for=()):
        self.access_token = access_token
        self.team_id = team_id
        self._messages_by_channel = messages_by_channel or {}
        self._error_for = set(error_for)
        self.messages_requested_for: list[str] = []

    def list_messages(self, channel_id):
        self.messages_requested_for.append(channel_id)
        if channel_id in self._error_for:
            request = httpx.Request("GET", "https://graph.microsoft.com/v1.0/teams/t/channels/c/messages/delta")
            response = httpx.Response(403, request=request, text="Forbidden")
            raise httpx.HTTPStatusError("403 Forbidden", request=request, response=response)
        return MessagePage(
            messages=self._messages_by_channel.get(channel_id, []), delta_token="tok-1", has_more=False,
        )


def test_run_smoke_test_reports_when_nothing_is_allowlisted(tmp_path, capsys):
    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok",
        team_id="team-1",
        reader_factory=lambda access_token, team_id: _FakeGraphReader(access_token, team_id),
        config_store=_config_store(tmp_path),
    )

    assert exit_code == 0
    assert "No channels are allowlisted" in capsys.readouterr().out


def test_run_smoke_test_reads_one_page_from_an_allowlisted_channel(tmp_path, capsys):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, ALLOWLISTED_CHANNEL_ID)

    fake = _FakeGraphReader(
        "tok",
        "team-1",
        messages_by_channel={
            ALLOWLISTED_CHANNEL_ID: [
                TeamsMessage(
                    id="m1",
                    channel_id=ALLOWLISTED_CHANNEL_ID,
                    author_id="priya.sharma",
                    posted_at="2025-06-05T09:15:00Z",
                )
            ]
        },
    )

    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok",
        team_id="team-1",
        reader_factory=lambda access_token, team_id: fake,
        config_store=ChannelConfigStore(config_dir),
    )

    assert exit_code == 0
    assert fake.messages_requested_for == [ALLOWLISTED_CHANNEL_ID]
    out = capsys.readouterr().out
    assert "priya.sharma" in out
    assert "2025-06-05T09:15:00Z" in out
    assert "Live Graph connection confirmed" in out


def test_run_smoke_test_reports_connected_but_empty_channel(tmp_path, capsys):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, ALLOWLISTED_CHANNEL_ID)

    fake = _FakeGraphReader("tok", "team-1", messages_by_channel={ALLOWLISTED_CHANNEL_ID: []})

    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok",
        team_id="team-1",
        reader_factory=lambda access_token, team_id: fake,
        config_store=ChannelConfigStore(config_dir),
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "zero messages returned" in out
    assert "Live Graph connection confirmed" in out


def test_run_smoke_test_reports_graph_rejection_and_fails_when_nothing_confirms(tmp_path, capsys):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, ALLOWLISTED_CHANNEL_ID)

    fake = _FakeGraphReader("tok", "team-1", error_for=[ALLOWLISTED_CHANNEL_ID])

    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok",
        team_id="team-1",
        reader_factory=lambda access_token, team_id: fake,
        config_store=ChannelConfigStore(config_dir),
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "Graph rejected this channel_id" in out
    assert "Live Graph connection confirmed" not in out


def test_run_smoke_test_confirms_the_channels_that_work_even_if_another_is_rejected(tmp_path, capsys):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, ALLOWLISTED_CHANNEL_ID)
    _write_config(config_dir, SECOND_ALLOWLISTED_CHANNEL_ID)

    fake = _FakeGraphReader(
        "tok",
        "team-1",
        messages_by_channel={SECOND_ALLOWLISTED_CHANNEL_ID: []},
        error_for=[ALLOWLISTED_CHANNEL_ID],
    )

    exit_code = graph_smoke_test.run_smoke_test(
        access_token="tok",
        team_id="team-1",
        reader_factory=lambda access_token, team_id: fake,
        config_store=ChannelConfigStore(config_dir),
    )

    assert exit_code == 0  # at least one channel_id was genuinely confirmed
    out = capsys.readouterr().out
    assert "Graph rejected this channel_id" in out
    assert "Live Graph connection confirmed" in out


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
