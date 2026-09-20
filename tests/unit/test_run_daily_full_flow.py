"""
CHN-31: proves scripts/run_daily.py's real full-flow entry point --
ingest -> detect -> ledger -> digest -> approval -> publish -- against
the real committed CHN-07 fixtures, calling the identical
run_full_flow() a clean clone's `make run` actually invokes. A
ScriptedGateway stands in for the real Anthropic call here, the same
substitution every other test in this project already makes -- this
project's own standing rule is that a live model call is never part of
its own verification (see DECISION_LOG.md's CHN-31 entry), not that the
real entry point itself avoids one.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is not a package -- add it to sys.path the same way
# scripts/run_daily.py itself adds src/ to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_daily

from p1.adapters.teams_publisher_mock import LogPublisher
from p1.llm.gateway import LLMResponse

ALPHA = "19:proj-alpha@thread.tacv2"
BETA = "19:proj-beta@thread.tacv2"
# Added alongside CHN-01's real Teams connection work: a genuine third
# allowlisted channel (config/channels/p1-agent-test.yaml), not a
# fixture -- this repo now has 3 real allowlisted channels, not 2, and
# this test's own job is to prove the demo touches exactly the real,
# current allowlist (see the ALPHA/BETA-only assertion this constant
# replaces, and DECISION_LOG.md's entry for this channel's addition).
P1_AGENT_TEST = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"
# Added 2026-09-20 alongside the SPN-04 multi-channel isolation test: a
# second real allowlisted channel (config/channels/teams-agent-test.yaml)
# -- this repo now has 4 real allowlisted channels, not 3, same reasoning
# as P1_AGENT_TEST's own comment above.
TEAMS_AGENT_TEST = "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2"

# CHN-09's classifier tool name (src/p1/detection/classifier.py) vs.
# CHN-13's daily-summary-section tool name (src/p1/reporting/daily_summary.py)
# -- generate_structured() always asks via tool_choice={"name": ...}, so
# that name is what tells this fake which schema the caller actually
# needs answered, never prompt-text sniffing.
_CLASSIFICATION_TOOL = "classification"


class ScriptedGateway:
    """Never a live call. A classification request gets a safe "update"
    label; anything else (the daily-summary-section request CHN-13's
    prose step makes) gets an empty, always-valid `{"lines": []}` --
    DailySummarySectionDraft.lines has no minimum length, and an empty
    section is exactly what this module's own docstring already calls
    an honest, legitimate output ("no updates were posted"), not a
    shortcut invented for this test."""

    def generate(self, prompt, **kwargs):
        tool_name = (kwargs.get("tool_choice") or {}).get("name")
        if tool_name == _CLASSIFICATION_TOOL:
            text = '{"label": "update", "confidence": 0.9}'
        else:
            text = '{"lines": []}'
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def test_run_full_flow_runs_all_allowlisted_channels_end_to_end(tmp_path):
    db_path = str(tmp_path / "test.db")
    log_path = tmp_path / "outbound_log.jsonl"

    results = run_daily.run_full_flow(
        db_path=db_path,
        gateway=ScriptedGateway(),
        publisher=LogPublisher(log_path=log_path),
        day=run_daily.DEMO_DAY,
    )

    channel_ids = {r.channel_id for r in results}
    assert channel_ids == {ALPHA, BETA, P1_AGENT_TEST, TEAMS_AGENT_TEST}, "gamma is not allowlisted and must never appear here"
    assert all(r.date == run_daily.DEMO_DAY.isoformat() for r in results)

    # A brand-new DB's very first publish for each channel is always left
    # PENDING for a human -- run_daily_digest_job's own first-publish
    # approval gate (CHN-17) -- so a fresh demo run against an empty DB
    # reports awaiting_approval for both channels, never a silent,
    # unapproved send.
    assert {r.status for r in results} == {"awaiting_approval"}

    # guarded_send() refuses a still-PENDING proposal before it ever
    # reaches the publisher, so LogPublisher's own append-only log must
    # stay untouched -- proof this run really did stop at the approval
    # gate rather than silently posting anyway.
    assert not log_path.exists()


def test_run_full_flow_auto_approves_and_publishes_on_a_later_day(tmp_path):
    """CHN-17's own rule: a channel's first-ever publish needs a human
    (proven above); once that first publish has actually gone out,
    every later day auto-approves and sends unattended, with no second
    human step. approve() alone does not make has_ever_published() true
    -- only a real send (digest_store.mark_published(), inside
    run_daily_digest_job's own success path) does -- so this test
    re-runs the approved first day before checking the second day,
    rather than asserting on approval status alone."""
    db_path = str(tmp_path / "test.db")
    log_path = tmp_path / "outbound_log.jsonl"
    gateway = ScriptedGateway()

    first_day_results = run_daily.run_full_flow(
        db_path=db_path, gateway=gateway,
        publisher=LogPublisher(log_path=log_path), day=run_daily.DEMO_DAY,
    )
    assert {r.status for r in first_day_results} == {"awaiting_approval"}
    assert not log_path.exists()

    from p1.approval.proposals import ProposalStore

    store = ProposalStore(db_path)
    for channel_id in (ALPHA, BETA, P1_AGENT_TEST, TEAMS_AGENT_TEST):
        key = f"{channel_id}:{run_daily.DEMO_DAY.isoformat()}:daily_publish"
        proposal = store.get_by_idempotency_key(key)
        store.approve(proposal.id, approver_id="test:human")

    # Re-running the SAME (now-approved) day is what actually sends it --
    # guarded_send() re-checks APPROVED and this time succeeds.
    first_day_rerun = run_daily.run_full_flow(
        db_path=db_path, gateway=gateway,
        publisher=LogPublisher(log_path=log_path), day=run_daily.DEMO_DAY,
    )
    assert {r.status for r in first_day_rerun} == {"published"}
    assert log_path.exists()
    assert len(log_path.read_text().strip().splitlines()) == 4  # one per channel

    # NOW has_ever_published() is true for all four channels, so the
    # next working day auto-approves and sends with no human step at all.
    later_day = run_daily.date(2025, 6, 12)
    second_day_results = run_daily.run_full_flow(
        db_path=db_path, gateway=gateway,
        publisher=LogPublisher(log_path=log_path), day=later_day,
    )
    assert {r.status for r in second_day_results} == {"published"}
    logged = log_path.read_text().strip().splitlines()
    assert len(logged) == 8  # 4 from the first day's rerun + 4 more here
