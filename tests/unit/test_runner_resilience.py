"""
Resilience added 2026-09-24 after a digest preview -- and, had it been the
real job, the 17:30 digest -- timed out waiting for a local model that a live
runner's 5-minute tick kept busy:

  - the live runners' publishing jobs are wrapped so a failure is retried and
    logged, never raised into APScheduler where it would vanish;
  - the Ollama request timeout is configurable and longer than the old fixed 60s.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import live_runner_p1_agent_test as runner

from spine.llm.gateway import LLMGateway


@pytest.fixture
def logs(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(runner, "_log", lines.append)
    slept: list[float] = []
    monkeypatch.setattr(runner.time, "sleep", slept.append)
    return SimpleNamespace(lines=lines, slept=slept)


def _result(status="published"):
    return SimpleNamespace(date="2026-09-24", status=status, detail="sent")


def test_a_job_that_succeeds_first_time_runs_once_and_is_logged(logs):
    calls = []
    runner._run_with_retries("digest", lambda **kw: calls.append(kw) or _result(), {"a": 1})
    assert calls == [{"a": 1}]
    assert logs.slept == []
    assert any("[digest] 2026-09-24: published" in line for line in logs.lines)


def test_a_transient_failure_is_retried_and_then_succeeds(logs):
    attempts = []

    def flaky(**kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("Ollama request failed: timed out")
        return _result()

    runner._run_with_retries("digest", flaky, {})
    assert len(attempts) == 3
    assert logs.slept == [runner._JOB_RETRY_WAIT_SECONDS] * 2
    assert sum("FAILED" in line for line in logs.lines) == 2
    assert any("published" in line for line in logs.lines)


def test_a_job_that_always_fails_gives_up_loudly_and_never_raises(logs):
    def broken(**kwargs):
        raise RuntimeError("timed out")

    runner._run_with_retries("weekly", broken, {})  # must not raise
    assert sum("FAILED" in line for line in logs.lines) == runner._JOB_ATTEMPTS
    assert any("gave up" in line and "run_live_pipeline_p1_agent_test.py" in line for line in logs.lines)


def test_ollama_timeout_defaults_to_180_seconds_not_the_old_60(monkeypatch):
    monkeypatch.delenv("OLLAMA_TIMEOUT_SECONDS", raising=False)
    assert LLMGateway(provider="ollama").ollama_timeout == 180.0


def test_ollama_timeout_can_be_overridden_from_the_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "300")
    assert LLMGateway(provider="ollama").ollama_timeout == 300.0
