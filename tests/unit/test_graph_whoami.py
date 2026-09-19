"""
Proves scripts/graph_whoami.py's real-identity diagnostic prints the
fields it claims to, and fails cleanly without a token -- without ever
opening a real Graph connection. Every test injects a fake http_get via
run_whoami's own seam, the same pattern
tests/unit/test_graph_smoke_test.py uses for its reader_factory.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import graph_whoami

_REQUEST = httpx.Request("GET", "https://graph.microsoft.com/v1.0/me")


def test_run_whoami_prints_the_real_identity_fields(capsys):
    def fake_http_get(access_token):
        assert access_token == "tok"
        return httpx.Response(
            200,
            request=_REQUEST,
            json={
                "id": "8ea0e38b-efb3-4757-924a-5f94061cf8c2",
                "userPrincipalName": "SharonS@digitalt3.com",
                "displayName": "Sharon Silva",
                "mail": "SharonS@digitalt3.com",
            },
        )

    exit_code = graph_whoami.run_whoami(access_token="tok", http_get=fake_http_get)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "8ea0e38b-efb3-4757-924a-5f94061cf8c2" in out
    assert "SharonS@digitalt3.com" in out
    assert "Sharon Silva" in out


def test_run_whoami_raises_on_a_graph_rejection():
    def fake_http_get(access_token):
        return httpx.Response(401, request=_REQUEST, text="Unauthorized")

    try:
        graph_whoami.run_whoami(access_token="expired-tok", http_get=fake_http_get)
        raise AssertionError("expected an HTTPStatusError")
    except httpx.HTTPStatusError:
        pass


def test_main_fails_cleanly_when_token_missing(monkeypatch, capsys):
    monkeypatch.delenv("GRAPH_ACCESS_TOKEN", raising=False)

    exit_code = graph_whoami.main()

    assert exit_code == 1
    assert "GRAPH_ACCESS_TOKEN must be set" in capsys.readouterr().out


def test_main_delegates_to_run_whoami_with_the_env_token(monkeypatch):
    monkeypatch.setenv("GRAPH_ACCESS_TOKEN", "tok-from-env")
    seen = {}

    def fake_run_whoami(*, access_token):
        seen["access_token"] = access_token
        return 0

    monkeypatch.setattr(graph_whoami, "run_whoami", fake_run_whoami)

    exit_code = graph_whoami.main()

    assert exit_code == 0
    assert seen == {"access_token": "tok-from-env"}
