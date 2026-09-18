"""
CHN-32: proves scripts/run_walkthrough.py's real walkthrough entry
point actually runs, end to end, against the real committed fixtures --
ingest+refusal, rule/classifier decisions, the ledger's three states,
the daily summary, the weekly roll-up, a held nudge and a rejected one,
and a real escalation evidence bundle -- using a scripted (never live)
gateway, the same discipline CHN-31's own test_run_daily_full_flow.py
already established.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_walkthrough

from p1.adapters.teams_publisher_mock import LogPublisher
from p1.llm.gateway import LLMResponse

_MESSAGE_ID_RE = re.compile(r"message_id:\s*(\S+)")


class ScriptedGateway:
    """Classification gets a safe "update" label. Weekly narrative gets
    a fixed sentence. Daily-summary-section calls echo back the FIRST
    real message_id p1.reporting.facts.render_facts_block actually put
    in the prompt (grounding requires an exact echo, never an invented
    one) so beat 5's permalink-rendering path is genuinely exercised,
    not skipped via an always-valid empty response. Everything else
    gets an empty, always-valid response."""

    def generate(self, prompt, **kwargs):
        tool_name = (kwargs.get("tool_choice") or {}).get("name")
        if tool_name == "classification":
            text = '{"label": "update", "confidence": 0.9}'
        elif tool_name == "weekly_narrative":
            text = '{"narrative": "A quiet week overall."}'
        elif tool_name == "daily_summary_section":
            match = _MESSAGE_ID_RE.search(prompt)
            if match:
                text = json.dumps({"lines": [{"message_id": match.group(1), "text": "Something happened.", "quote": None}]})
            else:
                text = '{"lines": []}'
        else:
            text = '{"lines": []}'
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def test_walkthrough_runs_every_beat_end_to_end(tmp_path, capsys):
    db_path = str(tmp_path / "test.db")
    log_path = tmp_path / "outbound_log.jsonl"

    run_walkthrough.run_walkthrough(
        db_path=db_path,
        gateway=ScriptedGateway(),
        publisher=LogPublisher(log_path=log_path),
    )

    out = capsys.readouterr().out

    # Beat 1: both real channels ingested, gamma named as never attempted
    assert "ingested 19:proj-alpha@thread.tacv2" in out
    assert "ingested 19:proj-beta@thread.tacv2" in out
    assert "refused, as expected" in out

    # Beat 2: both synthetic chat ids refused
    assert out.count("refused, as expected") >= 3  # gamma + 2 chats

    # Beat 3: a real rule decision and a real classifier decision
    assert "RULE decision" in out
    assert "CLASSIFIER decision" in out

    # Beat 4: all three ledger states present for the chosen real day
    assert "excluded: ['liam.oconnor']" in out
    assert "no_message:" in out
    assert "posted_no_update:" in out

    # Beat 5: a real permalink line, with the live-vs-mock narration cue
    assert "https://teams.microsoft.com" in out
    assert "Graph consent is still pending" in out

    # Beat 6: the weekly roll-up rendered
    assert "Weekly Roll-up" in out

    # Beat 7: sofia held then sent, amara rejected
    assert "sofia.almeida: awaiting_approval" in out
    assert "sofia.almeida: sent" in out
    assert "amara.okonkwo: rejected" in out

    # Beat 8: a real escalation evidence bundle, citing both real dates
    assert "sofia.almeida: awaiting_approval -- awaiting human approval" in out
    assert "2025-06-05: no message at all" in out
    assert "2025-06-06: no message at all" in out

    logged = log_path.read_text().strip().splitlines() if log_path.exists() else []
    assert len(logged) >= 1  # sofia's day-2 nudge really got sent
