"""
Proves scripts/graph_login.py's device-code sign-in glue -- argument
construction, error handling, and the in-place .env rewrite -- without
ever starting a real device-code flow or contacting Microsoft. Every
test substitutes a fake MSAL app via acquire_token's app_factory seam,
the same "written and tested against a fake, never run live under
test" discipline as GraphTeamsReader and PowerAutomateTeamsPublisher.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import graph_login
import pytest


class _FakeMsalApp:
    """Stands in for msal.PublicClientApplication. flow_response and
    token_response are handed back verbatim, so each test can shape
    exactly the MSAL behaviour it wants to exercise."""

    def __init__(self, client_id, authority, flow_response=None, token_response=None):
        self.client_id = client_id
        self.authority = authority
        self._flow_response = flow_response if flow_response is not None else {
            "user_code": "ABC123",
            "message": "Go to https://microsoft.com/devicelogin and enter ABC123",
        }
        self._token_response = token_response if token_response is not None else {
            "access_token": "fake-token-xyz",
            "expires_in": 3600,
        }
        self.scopes_requested = None

    def initiate_device_flow(self, scopes):
        self.scopes_requested = scopes
        return self._flow_response

    def acquire_token_by_device_flow(self, flow):
        return self._token_response


def _factory(flow_response=None, token_response=None):
    def make(client_id, authority):
        return _FakeMsalApp(client_id, authority, flow_response=flow_response, token_response=token_response)
    return make


def test_acquire_token_happy_path_returns_result_and_requests_right_scope(capsys):
    result = graph_login.acquire_token(
        tenant_id="tenant-123",
        client_id="client-456",
        app_factory=_factory(),
    )
    assert result["access_token"] == "fake-token-xyz"
    captured = capsys.readouterr()
    assert "ABC123" in captured.out


def test_acquire_token_requests_channel_message_read_all_scope():
    made = {}

    def make(client_id, authority):
        app = _FakeMsalApp(client_id, authority)
        made["app"] = app
        return app

    graph_login.acquire_token(tenant_id="t", client_id="c", app_factory=make)
    assert made["app"].scopes_requested == ["ChannelMessage.Read.All"]
    assert made["app"].authority == "https://login.microsoftonline.com/t"


def test_acquire_token_raises_when_device_flow_wont_start():
    with pytest.raises(graph_login.DeviceFlowError, match="Could not start device flow"):
        graph_login.acquire_token(
            tenant_id="t",
            client_id="c",
            app_factory=_factory(flow_response={"error": "invalid_client", "error_description": "bad app"}),
        )


def test_acquire_token_raises_when_sign_in_never_completes():
    with pytest.raises(graph_login.DeviceFlowError, match="Sign-in did not produce a token"):
        graph_login.acquire_token(
            tenant_id="t",
            client_id="c",
            app_factory=_factory(token_response={"error": "authorization_pending", "error_description": "still waiting"}),
        )


def test_write_token_to_env_appends_when_no_existing_line(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=sk-real\nLLM_PROVIDER=anthropic\n")

    graph_login.write_token_to_env("brand-new-token", env_path=env_path)

    lines = env_path.read_text().splitlines()
    assert "ANTHROPIC_API_KEY=sk-real" in lines
    assert "LLM_PROVIDER=anthropic" in lines
    assert "GRAPH_ACCESS_TOKEN=brand-new-token" in lines


def test_write_token_to_env_replaces_existing_line_in_place(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "ANTHROPIC_API_KEY=sk-real\n"
        "GRAPH_ACCESS_TOKEN=stale-old-token\n"
        "GRAPH_TEAM_ID=team-1\n"
    )

    graph_login.write_token_to_env("fresh-token", env_path=env_path)

    lines = env_path.read_text().splitlines()
    assert lines == [
        "ANTHROPIC_API_KEY=sk-real",
        "GRAPH_ACCESS_TOKEN=fresh-token",
        "GRAPH_TEAM_ID=team-1",
    ]


def test_write_token_to_env_creates_file_when_none_exists(tmp_path):
    env_path = tmp_path / ".env"
    assert not env_path.exists()

    graph_login.write_token_to_env("first-token", env_path=env_path)

    assert env_path.read_text().splitlines() == ["GRAPH_ACCESS_TOKEN=first-token"]


def test_main_fails_cleanly_when_azure_env_vars_missing(monkeypatch, capsys):
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.delenv("AZURE_CLIENT_ID", raising=False)

    exit_code = graph_login.main()

    assert exit_code == 1
    assert "AZURE_TENANT_ID and AZURE_CLIENT_ID" in capsys.readouterr().out


def test_main_happy_path_writes_env_and_reports_expiry(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-1")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-1")
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=sk-real\n")
    monkeypatch.setattr(graph_login, "ENV_PATH", env_path)
    monkeypatch.setattr(
        graph_login,
        "acquire_token",
        lambda *, tenant_id, client_id: {"access_token": "live-token", "expires_in": 3600},
    )

    exit_code = graph_login.main()

    assert exit_code == 0
    assert "GRAPH_ACCESS_TOKEN=live-token" in env_path.read_text()
    assert "60 minutes" in capsys.readouterr().out


def test_main_reports_sign_in_failure_without_touching_env(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-1")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-1")
    env_path = tmp_path / ".env"
    env_path.write_text("ANTHROPIC_API_KEY=sk-real\n")
    monkeypatch.setattr(graph_login, "ENV_PATH", env_path)

    def raise_error(*, tenant_id, client_id):
        raise graph_login.DeviceFlowError("admin consent still pending")

    monkeypatch.setattr(graph_login, "acquire_token", raise_error)

    exit_code = graph_login.main()

    assert exit_code == 1
    assert "admin consent still pending" in capsys.readouterr().out
    assert env_path.read_text() == "ANTHROPIC_API_KEY=sk-real\n"
