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


# --- startup waits for the internet; catch-up never raises (2026-09-24) ---------------

def test_startup_waits_for_the_internet_instead_of_crashing(monkeypatch, logs):
    from requests.exceptions import ConnectionError as NoInternet

    attempts = []

    def flaky_token(**kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise NoInternet("Failed to resolve 'login.microsoftonline.com'")
        return "token"

    monkeypatch.setattr(runner, "get_access_token", flaky_token)
    runner._wait_for_token("tenant", "client")
    assert len(attempts) == 3
    assert logs.slept == [runner._NETWORK_WAIT_SECONDS] * 2
    assert sum("No internet yet" in line for line in logs.lines) == 2


def test_a_real_auth_failure_is_not_mistaken_for_no_internet(monkeypatch, logs):
    def denied(**kwargs):
        raise runner.GraphAuthError("refresh token revoked")

    monkeypatch.setattr(runner, "get_access_token", denied)
    with pytest.raises(runner.GraphAuthError):
        runner._wait_for_token("tenant", "client")
    assert logs.slept == []


def test_catch_up_logs_what_it_ran(monkeypatch, logs):
    monkeypatch.setattr(runner, "run_missed_publishing", lambda **kw: [("digest", _result())])
    runner._catch_up(config=None)
    assert any("[catch-up] digest 2026-09-24: published" in line for line in logs.lines)


def test_catch_up_never_raises_and_says_it_will_retry(monkeypatch, logs):
    def boom(**kwargs):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(runner, "run_missed_publishing", boom)
    runner._catch_up(config=None)  # must not raise
    assert any("[catch-up] FAILED, will retry next tick" in line for line in logs.lines)


def test_the_gave_up_message_points_at_the_catch_up_check(logs):
    def broken(**kwargs):
        raise RuntimeError("timed out")

    runner._run_with_retries("digest", broken, {})
    assert any("catch-up check retries" in line for line in logs.lines)


# --- a digest is built from fresh data, or not at all (2026-09-24) ---------------------

def test_fresh_data_is_pulled_before_every_publishing_attempt(monkeypatch, logs):
    order = []
    monkeypatch.setattr(runner, "_PRE_PUBLISH_REFRESH", lambda: order.append("refresh"))
    runner._run_with_retries("digest", lambda **kw: order.append("job") or _result(), {})
    assert order == ["refresh", "job"]


def test_if_the_refresh_fails_no_digest_is_built_on_stale_data(monkeypatch, logs):
    """The whole point: a failed pull must NOT fall through to generating a digest from
    whatever is already stored."""
    job_calls = []

    def no_internet():
        raise ConnectionError("Failed to resolve 'graph.microsoft.com'")

    monkeypatch.setattr(runner, "_PRE_PUBLISH_REFRESH", no_internet)
    runner._run_with_retries("digest", lambda **kw: job_calls.append(1) or _result(), {})  # must not raise

    assert job_calls == []
    assert sum("FAILED" in line for line in logs.lines) == runner._JOB_ATTEMPTS
    assert any("gave up" in line for line in logs.lines)


def test_once_the_internet_is_back_the_retry_refreshes_then_publishes(monkeypatch, logs):
    attempts = []

    def flaky_refresh():
        attempts.append(1)
        if len(attempts) == 1:
            raise ConnectionError("down")

    job_calls = []
    monkeypatch.setattr(runner, "_PRE_PUBLISH_REFRESH", flaky_refresh)
    runner._run_with_retries("digest", lambda **kw: job_calls.append(1) or _result(), {})

    assert len(attempts) == 2 and job_calls == [1]
    assert any("published" in line for line in logs.lines)


def test_catch_up_hands_the_refresh_to_the_catch_up_logic(monkeypatch, logs):
    marker = lambda: None
    seen = {}
    monkeypatch.setattr(runner, "_PRE_PUBLISH_REFRESH", marker)
    monkeypatch.setattr(runner, "run_missed_publishing", lambda **kw: seen.update(kw) or [])
    runner._catch_up(config=None)
    assert seen["before"] is marker


def test_the_poll_tick_still_never_raises_and_skips_the_mirror_when_ingest_fails(monkeypatch, logs):
    mirrored = []
    monkeypatch.setattr(runner, "_sync_supabase_mirror", lambda db: mirrored.append(db))

    def boom(**kwargs):
        raise ConnectionError("down")

    monkeypatch.setattr(runner, "_ingest_and_classify", boom)
    runner._poll_ingest(tenant_id="t", client_id="c", team_id="x", gateway=None, db_path="db")  # must not raise
    assert any("[ingest] FAILED" in line for line in logs.lines)
    assert mirrored == []


def test_the_poll_tick_reports_an_auth_problem_as_skipped(monkeypatch, logs):
    def denied(**kwargs):
        raise runner.GraphAuthError("token expired")

    monkeypatch.setattr(runner, "_ingest_and_classify", denied)
    runner._poll_ingest(tenant_id="t", client_id="c", team_id="x", gateway=None, db_path="db")
    assert any("[ingest] SKIPPED" in line for line in logs.lines)
