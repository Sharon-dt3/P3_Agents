"""
Proves scripts/run_live_pipeline_p1_agent_test.py's real ingest ->
classify -> digest -> approval -> publish glue -- against a fake Graph
reader, a scripted LLM gateway, and a mock LogPublisher -- never a real
Graph connection, a real model call, or a real Teams post. Same
discipline as tests/unit/test_run_daily_full_flow.py (which this
mirrors for the live, single-channel path) and
tests/unit/test_run_live_ingest_p1_agent_test.py (whose _FakeGraphReader
shape this reuses).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_live_pipeline_p1_agent_test as live_pipeline

from p1.adapters.teams_publisher_mock import LogPublisher
from p1.adapters.teams_reader import MessagePage, TeamsMessage
from p1.approval.proposals import ProposalStore
from p1.governance.scope_gate import ScopeViolationError
from p1.llm.gateway import LLMResponse

_CLASSIFICATION_TOOL = "classification"


class _FakeGraphReader:
    def __init__(self, access_token, team_id, pages=None):
        self.access_token = access_token
        self.team_id = team_id
        self._pages = list(pages or [])
        self.calls = 0

    def list_messages(self, channel_id, since=None, delta_token=None):
        page = self._pages[self.calls]
        self.calls += 1
        return page


class ScriptedGateway:
    """Never a live call -- see test_run_daily_full_flow.py's own
    ScriptedGateway, which this mirrors: a classification request
    always gets a safe "update" label, everything else (the
    daily-summary-section request) gets an empty, always-valid
    `{"lines": []}`."""

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


def _human_message(msg_id: str, posted_at: str) -> TeamsMessage:
    # author_id must exactly match config/channels/p1-agent-test.yaml's
    # real roster entry. That entry is Sharon's real Azure AD object id
    # ("a52e61e5-16c6-4f6c-af67-f41f85e7a00a"), not her email -- CHN-25
    # found that GraphTeamsReader._parse_message() sets author_id from
    # Graph's from.user.id (an AAD GUID), which a roster written as an
    # email string can never match. This fixture originally used the
    # email directly (and, before that, a lowercase-mismatched email --
    # see this file's own earlier history in DECISION_LOG.md); both
    # were silently classified as noise by _rule_not_on_roster for two
    # different reasons before this fix.
    return TeamsMessage(
        id=msg_id,
        channel_id=live_pipeline.CHANNEL_ID,
        author_id="a52e61e5-16c6-4f6c-af67-f41f85e7a00a",
        posted_at=posted_at,
        is_bot=False,
        body="Finished the API integration today, no blockers.",
    )


def _bot_message(msg_id: str, posted_at: str) -> TeamsMessage:
    return TeamsMessage(
        id=msg_id,
        channel_id=live_pipeline.CHANNEL_ID,
        author_id=None,
        posted_at=posted_at,
        is_bot=True,
        body="Test message from P1 agent",
    )


def test_first_run_ingests_classifies_and_awaits_approval(tmp_path, capsys):
    db_path = str(tmp_path / "live.db")
    log_path = tmp_path / "outbound_log.jsonl"
    fake_reader = _FakeGraphReader(
        "tok", "team-1",
        pages=[
            MessagePage(
                messages=[_human_message("m1", "2025-06-11T09:00:00Z")],
                delta_token="tok-1", has_more=False,
            )
        ],
    )

    result = live_pipeline.run_live_pipeline(
        access_token="tok", team_id="team-1",
        day=live_pipeline.date(2025, 6, 11),  # a real Wednesday -- a working day
        db_path=db_path,
        reader_factory=lambda access_token, team_id: fake_reader,
        gateway=ScriptedGateway(),
        publisher=LogPublisher(log_path=log_path),
    )

    assert result.channel_id == live_pipeline.CHANNEL_ID
    assert result.status == "awaiting_approval"
    assert not log_path.exists(), "first-ever publish must never send unattended"

    out = capsys.readouterr().out
    assert "Ingested 1 new message(s)" in out
    assert "1 total non-deleted message(s)" in out
    assert "1 signal, 0 noise" in out


def test_bot_only_content_is_classified_as_noise_not_signal(tmp_path, capsys):
    db_path = str(tmp_path / "live.db")
    fake_reader = _FakeGraphReader(
        "tok", "team-1",
        pages=[
            MessagePage(
                messages=[_bot_message("m-bot", "2025-06-11T09:00:00Z")],
                delta_token="tok-1", has_more=False,
            )
        ],
    )

    live_pipeline.run_live_pipeline(
        access_token="tok", team_id="team-1",
        day=live_pipeline.date(2025, 6, 11),
        db_path=db_path,
        reader_factory=lambda access_token, team_id: fake_reader,
        gateway=ScriptedGateway(),
        publisher=LogPublisher(log_path=tmp_path / "outbound_log.jsonl"),
    )

    out = capsys.readouterr().out
    assert "0 signal, 1 noise" in out


def test_approving_the_first_publish_and_rerunning_actually_sends(tmp_path, capsys):
    db_path = str(tmp_path / "live.db")
    log_path = tmp_path / "outbound_log.jsonl"
    day = live_pipeline.date(2025, 6, 11)
    fake_reader = _FakeGraphReader(
        "tok", "team-1",
        pages=[
            MessagePage(
                messages=[_human_message("m1", "2025-06-11T09:00:00Z")],
                delta_token="tok-1", has_more=False,
            )
        ],
    )
    gateway = ScriptedGateway()

    first = live_pipeline.run_live_pipeline(
        access_token="tok", team_id="team-1", day=day, db_path=db_path,
        reader_factory=lambda access_token, team_id: fake_reader,
        gateway=gateway, publisher=LogPublisher(log_path=log_path),
    )
    assert first.status == "awaiting_approval"

    store = ProposalStore(db_path)
    key = f"{live_pipeline.CHANNEL_ID}:{day.isoformat()}:daily_publish"
    proposal = store.get_by_idempotency_key(key)
    store.approve(proposal.id, approver_id="test:human")

    # Re-ingesting the same page again is harmless (delta re-sync would
    # normally return nothing new against a real Graph channel); a
    # second fake page keeps this rerun from indexing past the list.
    fake_reader._pages.append(
        MessagePage(messages=[], delta_token="tok-2", has_more=False)
    )

    second = live_pipeline.run_live_pipeline(
        access_token="tok", team_id="team-1", day=day, db_path=db_path,
        reader_factory=lambda access_token, team_id: fake_reader,
        gateway=gateway, publisher=LogPublisher(log_path=log_path),
    )

    assert second.status == "published"
    assert log_path.exists()


def test_run_live_pipeline_only_ever_scopes_to_the_one_channel_id(tmp_path):
    # Same non-vacuousness discipline as
    # test_run_live_ingest_p1_agent_test.py's own scope-gate test:
    # exercises build_scoped_reader() -- the exact construction path
    # run_live_pipeline() itself uses -- not a second, hand-rolled
    # ScopedTeamsReader that would pass even if this script's own
    # wiring stopped scope-gating. run_live_pipeline() is called once
    # first (with a fake reader returning an empty page) purely so
    # init_db() creates sync_state/messages/etc. before this test
    # reaches into them directly -- mirroring
    # test_run_live_ingest_p1_agent_test.py's own
    # test_run_live_ingest_only_ever_scopes_to_the_one_channel_id.
    from p1.ingestion.sync import sync_channel
    from p1.storage.messages_repo import MessageStore
    from p1.storage.sync_state import SyncStateStore

    db_path = str(tmp_path / "live.db")
    fake_reader = _FakeGraphReader(
        "tok", "team-1", pages=[MessagePage(messages=[], delta_token="t", has_more=False)]
    )

    live_pipeline.run_live_pipeline(
        access_token="tok", team_id="team-1",
        day=live_pipeline.date(2025, 6, 11),
        db_path=db_path,
        reader_factory=lambda access_token, team_id: fake_reader,
        gateway=ScriptedGateway(),
        publisher=LogPublisher(log_path=tmp_path / "outbound_log.jsonl"),
    )

    reader = live_pipeline.build_scoped_reader(
        access_token="tok", team_id="team-1", db_path=db_path,
        reader_factory=lambda access_token, team_id: fake_reader,
    )
    try:
        sync_channel(reader, "19:proj-alpha@thread.tacv2", SyncStateStore(db_path), MessageStore(db_path))
        raise AssertionError("expected ScopeViolationError")
    except ScopeViolationError:
        pass
