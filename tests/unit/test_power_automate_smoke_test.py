"""
Proves scripts/power_automate_smoke_test.py posts the expected
channel_post to the expected real channel_id and surfaces
PowerAutomatePublishError as a clean failure -- without ever opening a
real HTTP connection to a Power Automate flow. Every test injects a
fake publisher via run_smoke_test's publisher_factory seam, the same
pattern scripts/graph_smoke_test.py and
scripts/run_live_ingest_p1_agent_test.py already use.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import power_automate_smoke_test

from p1.adapters.teams_publisher_power_automate import PowerAutomatePublishError


class _FakePublisher:
    def __init__(self, flow_url, *, response=None, raise_error: PowerAutomatePublishError | None = None):
        self.flow_url = flow_url
        self._response = response if response is not None else {"ok": True}
        self._raise_error = raise_error
        self.channel_posts: list[tuple[str, str]] = []

    def post_channel_message(self, channel_id, content):
        self.channel_posts.append((channel_id, content))
        if self._raise_error is not None:
            raise self._raise_error
        return self._response


def test_run_smoke_test_posts_to_the_real_p1_agent_test_channel(capsys):
    fake = _FakePublisher("https://example.invalid/flow")

    exit_code = power_automate_smoke_test.run_smoke_test(
        flow_url="https://example.invalid/flow",
        publisher_factory=lambda flow_url: fake,
    )

    assert exit_code == 0
    assert len(fake.channel_posts) == 1
    posted_channel_id, posted_content = fake.channel_posts[0]
    assert posted_channel_id == power_automate_smoke_test.CHANNEL_ID
    assert "P1 smoke test" in posted_content
    out = capsys.readouterr().out
    assert "Posted a test message" in out


def test_run_smoke_test_reports_a_flow_rejection_and_fails(capsys):
    fake = _FakePublisher(
        "https://example.invalid/flow",
        raise_error=PowerAutomatePublishError("Power Automate flow at '...' returned HTTP 500: boom"),
    )

    exit_code = power_automate_smoke_test.run_smoke_test(
        flow_url="https://example.invalid/flow",
        publisher_factory=lambda flow_url: fake,
    )

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "rejected the post" in out
    assert "Posted a test message" not in out


def test_main_fails_cleanly_when_flow_url_missing(monkeypatch, capsys):
    monkeypatch.delenv("POWER_AUTOMATE_FLOW_URL", raising=False)

    exit_code = power_automate_smoke_test.main()

    assert exit_code == 1
    assert "POWER_AUTOMATE_FLOW_URL must be set" in capsys.readouterr().out


def test_main_delegates_to_run_smoke_test_with_env_value(monkeypatch):
    monkeypatch.setenv("POWER_AUTOMATE_FLOW_URL", "https://example.invalid/flow-from-env")
    seen = {}

    def fake_run_smoke_test(*, flow_url):
        seen["flow_url"] = flow_url
        return 0

    monkeypatch.setattr(power_automate_smoke_test, "run_smoke_test", fake_run_smoke_test)

    exit_code = power_automate_smoke_test.main()

    assert exit_code == 0
    assert seen == {"flow_url": "https://example.invalid/flow-from-env"}
