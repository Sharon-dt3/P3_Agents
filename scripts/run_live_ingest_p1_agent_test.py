"""
CHN-01/CHN-05's first real, live ingestion run: syncs exactly one real,
already-verified channel -- config/channels/p1-agent-test.yaml's real
channel_id -- from the live Microsoft Graph tenant, through the exact
same production ingestion path (p1.ingestion.sync.sync_channel(),
scope-gated by CHN-04's ScopedTeamsReader) every mock-fixture run
already exercises. Unlike scripts/graph_smoke_test.py, this actually
persists what it reads.

Deliberately scoped to this one channel_id only, not
sync_all_allowlisted_channels() over the full config/channels/*.yaml
allowlist. That allowlist still carries proj-alpha and proj-beta,
whose channel_ids were never real Graph ids (mock fixtures) -- running
them for real crashes outright: GraphTeamsReader.list_messages()
raises DeltaTokenExpiredError for a channel_id Graph can't resolve at
all, sync_channel()'s one-shot retry (clear the token, resync from
scratch) can't fix an id that was never real to begin with, and the
second attempt's error propagates uncaught. Confirmed directly (a
throwaway repro script, not guessed at) before writing this file.
Deciding proj-alpha/proj-beta's real fate (real channel_ids of their
own, or dropped from the allowlist for good) is a separate, disclosed,
not-yet-decided question -- see DECISION_LOG.md -- and this script
does not depend on that decision either way.

Uses a DEDICATED database (data/p1_live.db by default) rather than the
shared data/p1.db every mock-fixture demo/eval script reads and
writes, so a real person's real Teams message content never lands in
the same store the mock-based test suite and golden-case eval harness
score against.

Requires GRAPH_ACCESS_TOKEN (scripts/graph_login.py) and GRAPH_TEAM_ID
in .env, exactly like scripts/graph_smoke_test.py.

Usage:
    uv run python scripts/run_live_ingest_p1_agent_test.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.governance.scope_gate import ScopedTeamsReader
from p1.ingestion.sync import sync_channel
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

LIVE_DB_PATH = "data/p1_live.db"
# config/channels/p1-agent-test.yaml's real channel_id -- verified live
# via scripts/graph_smoke_test.py earlier this session.
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"


def build_scoped_reader(
    *, access_token: str, team_id: str, db_path: str, reader_factory=GraphTeamsReader,
) -> ScopedTeamsReader:
    """The exact reader construction run_live_ingest() uses -- pulled out
    on its own so a test can call it directly and prove the real object
    this script builds refuses an out-of-scope channel_id, rather than a
    second, hand-rolled ScopedTeamsReader that would pass even if this
    function stopped scope-gating."""
    raw_reader = reader_factory(access_token=access_token, team_id=team_id)
    return ScopedTeamsReader(raw_reader, allowlisted_channel_ids=[CHANNEL_ID], db_path=db_path)


def run_live_ingest(
    *, access_token: str, team_id: str, db_path: str = LIVE_DB_PATH, reader_factory=GraphTeamsReader,
) -> int:
    """reader_factory is a seam for tests: production always builds the
    real GraphTeamsReader (the default), tests substitute a fake one
    that never opens a real network connection."""
    init_db(db_path)
    # sync_state.channel_id is a foreign key into the channels table,
    # which only ChannelConfigStore().sync_to_db() populates -- this
    # registers every configured channel's config (name, roster, timing)
    # into this dedicated db, not just CHANNEL_ID, but never attempts a
    # Graph read for any of them; only sync_channel() below does that,
    # and only for CHANNEL_ID.
    ChannelConfigStore().sync_to_db(db_path)

    reader = build_scoped_reader(
        access_token=access_token, team_id=team_id, db_path=db_path, reader_factory=reader_factory,
    )

    sync_state = SyncStateStore(db_path)
    message_store = MessageStore(db_path)

    result = sync_channel(reader, CHANNEL_ID, sync_state, message_store)
    resynced_note = " (resynced from scratch -- prior delta token had expired)" if result.resynced else ""
    print(f"Ingested {result.messages_ingested} message(s) from {result.channel_id}{resynced_note}.")

    conn = get_connection(db_path)
    try:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE channel_id = ?", (CHANNEL_ID,)
        ).fetchone()["n"]
    finally:
        conn.close()
    print(f"Total messages now stored for this channel in {db_path}: {total}")
    return 0


def main() -> int:
    access_token = os.environ.get("GRAPH_ACCESS_TOKEN")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not access_token or not team_id:
        print("GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID must both be set in .env -- run "
              "scripts/graph_login.py first.")
        return 1
    return run_live_ingest(access_token=access_token, team_id=team_id)


if __name__ == "__main__":
    raise SystemExit(main())
