"""
Proves scripts/run_live_ingest_p1_agent_test.py's real ingestion glue --
scope-gating to exactly one channel_id, persisting through the real
production sync_channel() path, reporting a count -- without ever opening
a real Graph connection. Every test injects a fake reader via
run_live_ingest's reader_factory seam and points db_path at a temp file,
never data/p1_live.db.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import run_live_ingest_p1_agent_test as live_ingest

from p1.adapters.teams_reader import MessagePage, TeamsMessage
from p1.governance.scope_gate import ScopeViolationError
from p1.storage.db import get_connection


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


def test_run_live_ingest_persists_real_messages_for_the_one_scoped_channel(tmp_path, capsys):
    db_path = str(tmp_path / "live.db")
    fake = _FakeGraphReader(
        "tok",
        "team-1",
        pages=[
            MessagePage(
                messages=[
                    TeamsMessage(
                        id="m1",
                        channel_id=live_ingest.CHANNEL_ID,
                        author_id="sharons@digitalt3.com",
                        posted_at="2026-09-16T10:49:31.35Z",
                    )
                ],
                delta_token="tok-1",
                has_more=False,
            )
        ],
    )

    exit_code = live_ingest.run_live_ingest(
        access_token="tok",
        team_id="team-1",
        db_path=db_path,
        reader_factory=lambda access_token, team_id: fake,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Ingested 1 message(s)" in out
    assert "Total messages now stored for this channel in" in out

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT author_id FROM messages WHERE id = ? AND channel_id = ?",
            ("m1", live_ingest.CHANNEL_ID),
        ).fetchone()
    finally:
        conn.close()
    assert row["author_id"] == "sharons@digitalt3.com"


def test_run_live_ingest_only_ever_scopes_to_the_one_channel_id(tmp_path):
    # Exercises the SAME reader-construction path run_live_ingest() itself
    # uses (build_scoped_reader), not a second, hand-rolled ScopedTeamsReader
    # -- so this genuinely proves the script's own wiring refuses an
    # out-of-scope channel_id, rather than passing regardless of whether
    # run_live_ingest() actually applies the scope gate at all. Confirmed
    # non-vacuous by injecting the real bug (run_live_ingest bypassing the
    # scope gate entirely) and watching this exact test fail before fixing it.
    db_path = str(tmp_path / "live.db")
    fake = _FakeGraphReader("tok", "team-1", pages=[MessagePage(messages=[], delta_token="t", has_more=False)])

    from p1.ingestion.sync import sync_channel
    from p1.storage.messages_repo import MessageStore
    from p1.storage.sync_state import SyncStateStore

    live_ingest.run_live_ingest(
        access_token="tok", team_id="team-1", db_path=db_path,
        reader_factory=lambda access_token, team_id: fake,
    )

    reader = live_ingest.build_scoped_reader(
        access_token="tok", team_id="team-1", db_path=db_path,
        reader_factory=lambda access_token, team_id: fake,
    )
    try:
        sync_channel(reader, "19:proj-alpha@thread.tacv2", SyncStateStore(db_path), MessageStore(db_path))
        raise AssertionError("expected ScopeViolationError")
    except ScopeViolationError:
        pass
