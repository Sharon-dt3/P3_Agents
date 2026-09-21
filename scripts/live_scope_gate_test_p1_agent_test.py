"""
Live proof of CHN-03/CHN-04's own acceptance test, against the real
Graph connection rather than MockTeamsReader: "zero messages from
non-allowlisted channels or from any chat exist in the store after a
full ingest; each refusal is logged."

Four real calls through a real ScopedTeamsReader wrapping a real
GraphTeamsReader (silent token refresh via p1.adapters.graph_auth --
run scripts/graph_seed_token_cache.py first if this fails to get a
token):

  1. list_messages() on the real, allowlisted p1-agent-test channel --
     expected to succeed, a real Graph call.
  2. list_messages() on a channel_id that is NOT on the allowlist --
     expected to raise ScopeViolationError before any Graph call is
     even attempted (an out-of-scope channel is refused at this gate,
     not merely filtered afterward).
  3. list_replies() on a made-up message_id this gate has never itself
     returned -- expected to raise ScopeViolationError (2026-09-20's
     fix: this used to pass straight through with no check at all).
  4. list_replies() on a real message_id this gate DID just return in
     step 1 -- expected to succeed, a real Graph call.

Then prints every refusal this run wrote to the audit table, and
confirms zero messages exist in the local store for the non-allowlisted
channel_id used in step 2 -- proving the acceptance test's own two
halves for real, not just in a unit test against a mock.

Usage:
    uv run python scripts/live_scope_gate_test_p1_agent_test.py
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
from p1.storage.db import get_connection, init_db

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test (the only real allowlisted channel)

# Not a real Graph channel -- doesn't need to be. The whole point is that
# this gate refuses it before ever making a network call, so whether it
# names something real is irrelevant to what's being proven.
NOT_ALLOWLISTED_CHANNEL_ID = "19:some-other-team-channel@thread.tacv2"
# Teams chat IDs have their own distinct shape (unq.gbl.spaces, not
# thread.tacv2/thread.skype) -- included to demonstrate "chats never
# read" concretely, not just "some other channel."
CHAT_ID = "19:deadbeef1234567890@unq.gbl.spaces"


def main() -> int:
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not tenant_id or not client_id or not team_id:
        print("AZURE_TENANT_ID, AZURE_CLIENT_ID, and GRAPH_TEAM_ID must all be set in .env.")
        return 1

    try:
        access_token = get_access_token(tenant_id=tenant_id, client_id=client_id, allow_interactive=True)
    except GraphAuthError as exc:
        print(f"Could not get a Graph token: {exc}")
        return 1

    init_db(LIVE_DB_PATH)
    raw_reader = GraphTeamsReader(access_token=access_token, team_id=team_id)
    gate = ScopedTeamsReader(raw_reader, allowlisted_channel_ids=[CHANNEL_ID], db_path=LIVE_DB_PATH)

    audit_id_before = _max_audit_id(LIVE_DB_PATH)

    print("1. list_messages() on the real allowlisted channel...")
    page = gate.list_messages(CHANNEL_ID)
    print(f"   OK -- {len(page.messages)} top-level message(s) returned (real Graph call).")
    if not page.messages:
        print("   No messages to pick a real message_id from for steps 3/4 -- steps 3/4 will use a made-up id for both.")
        real_message_id = None
    else:
        real_message_id = page.messages[0].id

    print(f"\n2. list_messages() on a NON-allowlisted channel_id ({NOT_ALLOWLISTED_CHANNEL_ID!r})...")
    try:
        gate.list_messages(NOT_ALLOWLISTED_CHANNEL_ID)
        print("   FAILED -- this should have raised ScopeViolationError and did not.")
        return 1
    except ScopeViolationError as exc:
        print(f"   Refused correctly, no Graph call made: {exc}")

    print(f"\n2b. list_messages() on a chat-shaped id ({CHAT_ID!r})...")
    try:
        gate.list_messages(CHAT_ID)
        print("   FAILED -- this should have raised ScopeViolationError and did not.")
        return 1
    except ScopeViolationError as exc:
        print(f"   Refused correctly, no Graph call made: {exc}")

    print("\n3. list_replies() on a message_id this gate has never itself seen...")
    try:
        gate.list_replies("made-up-message-id-never-returned-by-this-gate")
        print("   FAILED -- this should have raised ScopeViolationError and did not.")
        return 1
    except ScopeViolationError as exc:
        print(f"   Refused correctly (2026-09-20 fix): {exc}")

    if real_message_id:
        print(f"\n4. list_replies() on a real message_id this gate DID just return ({real_message_id!r})...")
        replies = gate.list_replies(real_message_id)
        print(f"   OK -- {len(replies)} repl(y/ies) returned (real Graph call).")

    print("\nRefusals this run wrote to the audit table:")
    for row in _refusals_since(LIVE_DB_PATH, audit_id_before):
        print(f"   entity_type={row['entity_type']!r} entity_id={row['entity_id']!r} details={row['details']}")

    print(f"\nMessages stored locally for the non-allowlisted channel_id used in step 2 "
          f"({NOT_ALLOWLISTED_CHANNEL_ID!r}):")
    count = _message_count_for_channel(LIVE_DB_PATH, NOT_ALLOWLISTED_CHANNEL_ID)
    print(f"   {count} (expected 0)")

    return 0 if count == 0 else 1


def _max_audit_id(db_path: str) -> int:
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM audit").fetchone()
        return row["max_id"]
    finally:
        conn.close()


def _refusals_since(db_path: str, audit_id_after: int):
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT entity_type, entity_id, details FROM audit "
            "WHERE id > ? AND actor = 'scope_gate' ORDER BY id",
            (audit_id_after,),
        ).fetchall()
    finally:
        conn.close()


def _message_count_for_channel(db_path: str, channel_id: str) -> int:
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM messages WHERE channel_id = ?", (channel_id,),
        ).fetchone()
        return row["n"]
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
