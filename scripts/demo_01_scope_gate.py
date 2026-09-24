"""
Recording beats 1 and 2 (CHN-32): ingest two real channels, refuse a
third, and refuse a chat -- all through the real production ingestion
entry point (p1.ingestion.sync.sync_channel) wrapped by the real scope
gate (ScopedTeamsReader), against the real Graph tenant.

The refusal is not asserted, it is measured: the real GraphTeamsReader's
list_messages is wrapped in a call recorder, so the script prints every
channel_id Graph was actually asked about. The two real channels appear;
the refused channel and the chat do not -- proof the gate stops them at
the adapter boundary, before any network call, not by filtering results
afterward.

Read-only against Teams (never posts). Ingesting the two real channels
writes to data/p1_live.db exactly as the live runners' 5-minute poll
already does; refusals write to the audit table.

Usage:
    uv run python scripts/demo_01_scope_gate.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.graph_auth import GraphAuthError, get_access_token
from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.governance.scope_gate import ScopedTeamsReader, ScopeViolationError
from p1.ingestion.sync import sync_channel
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

LIVE_DB_PATH = "data/p1_live.db"

P1_AGENT_TEST = ("p1-agent-test", "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2")
TEAMS_AGENT_TEST = ("Teams-agent-test", "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2")
ALLOWLIST = [P1_AGENT_TEST, TEAMS_AGENT_TEST]

# A real channel created in the same Team specifically for this demo, with
# a message posted in it and deliberately NO config/channels yaml -- so it
# is refused by default, not because a file says so.
REFUSED_CHANNEL = ("Non-Allowlisted Channel Test", "19:J3y5zEhYI_QgDokHcPFIaZh39R2UcXgACBsjt_TrdHI1@thread.tacv2")
# Teams chat ids have their own shape (unq.gbl.spaces, not thread.tacv2).
REFUSED_CHAT = ("a one-to-one/group chat", "19:deadbeef1234567890@unq.gbl.spaces")


def _stored_count(channel_id: str) -> int:
    conn = get_connection(LIVE_DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM messages WHERE channel_id = ?", (channel_id,)).fetchone()["n"]
    finally:
        conn.close()


def _max_audit_id() -> int:
    conn = get_connection(LIVE_DB_PATH)
    try:
        return conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM audit").fetchone()["m"]
    finally:
        conn.close()


def main() -> int:
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not tenant_id or not client_id or not team_id:
        print("AZURE_TENANT_ID, AZURE_CLIENT_ID, and GRAPH_TEAM_ID must all be set in .env.")
        return 1
    try:
        access_token = get_access_token(tenant_id=tenant_id, client_id=client_id, allow_interactive=False)
    except GraphAuthError as exc:
        print(f"Graph auth failed -- {exc}")
        return 1

    init_db(LIVE_DB_PATH)

    raw_reader = GraphTeamsReader(access_token=access_token, team_id=team_id)
    graph_calls: list[str] = []
    real_list_messages = raw_reader.list_messages

    def recording_list_messages(channel_id, *args, **kwargs):
        graph_calls.append(channel_id)
        return real_list_messages(channel_id, *args, **kwargs)

    raw_reader.list_messages = recording_list_messages

    gate = ScopedTeamsReader(raw_reader, allowlisted_channel_ids=[cid for _, cid in ALLOWLIST], db_path=LIVE_DB_PATH)
    sync_state = SyncStateStore(LIVE_DB_PATH)
    message_store = MessageStore(LIVE_DB_PATH)
    audit_before = _max_audit_id()

    print("=" * 78)
    print("The explicit allowlist for this run (exactly two real Teams channels):")
    for name, cid in ALLOWLIST:
        print(f"   - {name}  ({cid})")

    print()
    print("BEAT 1a/1b -- ingest the two allowlisted channels (real Graph, real delta sync)")
    for name, cid in ALLOWLIST:
        result = sync_channel(gate, cid, sync_state, message_store)
        note = " (full resync)" if result.resynced else ""
        print(f"   {name}: {result.messages_ingested} new message(s) this sync{note}; "
              f"{_stored_count(cid)} stored in total")

    print()
    print("BEAT 1c -- try to ingest a THIRD channel that is not on the allowlist")
    name, cid = REFUSED_CHANNEL
    from p1.config.loader import ChannelConfigStore

    has_config = any(c.channel_id == cid for c in ChannelConfigStore().list_configured_channels())
    print(f"   {name} is a real channel in this Team; config file for it: {'YES' if has_config else 'none'}")
    print(f"   attempting sync_channel() on {name} ({cid}) ...")
    try:
        sync_channel(gate, cid, sync_state, message_store)
        print("   FAILED -- this should have been refused.")
        return 1
    except ScopeViolationError as exc:
        print(f"   REFUSED: {exc}")

    print()
    print("BEAT 2 -- try to ingest a chat")
    name, cid = REFUSED_CHAT
    print(f"   attempting sync_channel() on {name} ({cid}) ...")
    try:
        sync_channel(gate, cid, sync_state, message_store)
        print("   FAILED -- this should have been refused.")
        return 1
    except ScopeViolationError as exc:
        print(f"   REFUSED: {exc}")

    print()
    print("PROOF -- what Graph was actually asked about during this run:")
    for cid in graph_calls:
        label = next((n for n, c in ALLOWLIST if c == cid), "?")
        print(f"   Graph list_messages() called for: {label}")
    refused_ids = {REFUSED_CHANNEL[1], REFUSED_CHAT[1]}
    leaked = refused_ids & set(graph_calls)
    print(f"   Graph calls made for the refused channel or the chat: {len(leaked)} (must be 0)")
    for name, cid in (REFUSED_CHANNEL, REFUSED_CHAT):
        print(f"   messages stored for {name}: {_stored_count(cid)} (must be 0)")

    print()
    print("PROOF -- the refusal records this run wrote to the audit table:")
    conn = get_connection(LIVE_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT entity_type, entity_id, details FROM audit WHERE id > ? AND actor = 'scope_gate' ORDER BY id",
            (audit_before,),
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        print(f"   {row['entity_type']} {row['entity_id']} -> {row['details']}")

    ok = not leaked and all(_stored_count(cid) == 0 for cid in refused_ids) and len(rows) == 2
    print()
    print("RESULT:", "PASS -- two channels ingested, third refused, chat refused, nothing leaked." if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
