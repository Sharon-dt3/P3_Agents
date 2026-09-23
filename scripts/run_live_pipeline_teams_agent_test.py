"""
The real, live, end-to-end run against the real teams-agent-test Teams
channel: ingest -> classify (CHN-08/09) -> build the participation
ledger and generate a digest (CHN-10/13) -> attempt to publish it
through the real Power Automate flow (CHN-22) -- via the exact same
production functions (sync_channel, classify_and_persist,
run_daily_digest_job) every mock-fixture test, GC6, and
scripts/run_daily.py already exercise. This is the second-channel
counterpart to scripts/run_live_pipeline_p1_agent_test.py, deliberately
its own file rather than a shared, parameterized script -- same
reasoning as that script's own docstring: p1-agent-test and
teams-agent-test are the only two allowlisted channels with real Graph
ids (proj-alpha/proj-beta remain mock-fixture ids and would crash if
ever pointed at Graph for real), so a per-channel script keeps that
distinction explicit and impossible to get wrong by a stray loop.

Shares data/p1_live.db with run_live_pipeline_p1_agent_test.py on
purpose: both are real channels (never mock-fixture content), .env's
P1_DB_PATH already points app/approval_dashboard.py at this same file,
and a single dashboard session approving both channels' pending
proposals is exactly what a real two-channel isolation test needs to
show side by side.

config/channels/teams-agent-test.yaml is America/New_York, working
days Mon-Fri, update window 09:00-13:00, nudge_enabled: false (unlike
p1-agent-test's temporarily-relaxed settings) -- its own real,
steady-state config, untouched by this script.

Same two things worth knowing before running this for real that
run_live_pipeline_p1_agent_test.py's own docstring already flags for
its channel, true here too:

1. ignore_bots: true means any bot-authored message in this channel
   contributes nothing to a digest -- a real, human-authored message
   is required for this script to look "useful." That is not this
   script's bug to fix; it requires a person actually posting in
   Teams, inside the 09:00-13:00 America/New_York window to land as an
   on-time update.

2. run_daily_digest_job's first-ever publish for any channel is always
   left awaiting_approval (DigestStore.has_ever_been_published() is
   False for a channel that has never published) -- that is the
   designed behaviour, not a failure. A human approves it separately,
   through app/approval_dashboard.py, then this script is run again to
   actually send.

Usage:
    uv run python scripts/run_live_pipeline_teams_agent_test.py [--day YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.factory import get_teams_publisher
from p1.adapters.graph_auth import GraphAuthError, get_access_token
from p1.adapters.teams_reader import TeamsMessage
from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.governance.scope_gate import ScopedTeamsReader
from p1.ingestion.sync import sync_channel
from p1.llm.gateway import LLMGateway
from p1.participation.ledger import build_and_persist_ledger
from p1.publishing.daily_job import SKIPPED_NON_WORKING_DAY, JobResult, run_daily_digest_job
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

# Shared with run_live_pipeline_p1_agent_test.py on purpose -- see this
# module's own docstring for why (both are real channels, one dashboard).
LIVE_DB_PATH = "data/p1_live.db"

# config/channels/teams-agent-test.yaml's real channel_id.
CHANNEL_ID = "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2"


def build_scoped_reader(
    *, access_token: str, team_id: str, db_path: str, reader_factory=GraphTeamsReader,
) -> ScopedTeamsReader:
    """Identical role to run_live_ingest_p1_agent_test.py's own helper
    of the same name -- pulled out so a test can call it directly and
    prove the real object this script builds refuses an out-of-scope
    channel_id, rather than a second, hand-rolled ScopedTeamsReader
    that would pass even if this function stopped scope-gating."""
    raw_reader = reader_factory(access_token=access_token, team_id=team_id)
    return ScopedTeamsReader(raw_reader, allowlisted_channel_ids=[CHANNEL_ID], db_path=db_path)


def _load_channel_messages(db_path: str, channel_id: str) -> list[TeamsMessage]:
    """Reconstructs TeamsMessage objects from every non-deleted row this
    channel currently has in `messages` -- classify_and_persist takes a
    list[TeamsMessage], and sync_channel() only ever returns a count,
    never the messages themselves, so this is the one read-back step a
    live run needs that a fixture-driven run (which already holds its
    TeamsMessage objects in memory) does not."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, channel_id, author_id, thread_root_id, posted_at,
                   edited_at, deleted_at, is_deleted, is_bot, is_system,
                   body_raw, permalink
            FROM messages
            WHERE channel_id = ? AND is_deleted = 0
            """,
            (channel_id,),
        ).fetchall()
    finally:
        conn.close()

    return [
        TeamsMessage(
            id=row["id"],
            channel_id=row["channel_id"],
            author_id=row["author_id"],
            thread_root_id=row["thread_root_id"],
            posted_at=row["posted_at"],
            edited_at=row["edited_at"],
            deleted_at=row["deleted_at"],
            is_deleted=bool(row["is_deleted"]),
            is_bot=bool(row["is_bot"]),
            is_system=bool(row["is_system"]),
            body=row["body_raw"] or "",
            permalink=row["permalink"],
        )
        for row in rows
    ]


def run_live_pipeline(
    *,
    access_token: str,
    team_id: str,
    day: date | None = None,
    db_path: str = LIVE_DB_PATH,
    reader_factory=GraphTeamsReader,
    gateway=None,
    publisher=None,
) -> JobResult:
    """reader_factory/gateway/publisher are seams for tests: production
    always builds the real GraphTeamsReader, LLMGateway, and whatever
    get_teams_publisher() resolves to from TEAMS_PUBLISHER_MODE (all
    three defaults), tests substitute fakes that never touch a real
    network, model, or Teams tenant."""
    init_db(db_path)
    # sync_state.channel_id and messages.author_id are both foreign
    # keys (channels.id, members.id respectively) -- sync_to_db()
    # registers every configured channel; author rows are handled
    # per-message by MessageStore itself.
    ChannelConfigStore().sync_to_db(db_path)

    reader = build_scoped_reader(
        access_token=access_token, team_id=team_id, db_path=db_path, reader_factory=reader_factory,
    )
    sync_state = SyncStateStore(db_path)
    message_store = MessageStore(db_path)
    sync_result = sync_channel(reader, CHANNEL_ID, sync_state, message_store)
    resynced_note = " (resynced from scratch -- prior delta token had expired)" if sync_result.resynced else ""
    print(f"Ingested {sync_result.messages_ingested} new message(s) from {CHANNEL_ID}{resynced_note}.")

    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    messages = _load_channel_messages(db_path, CHANNEL_ID)
    print(f"{len(messages)} total non-deleted message(s) known for this channel in {db_path}.")

    gateway = gateway or LLMGateway()
    publisher = publisher or get_teams_publisher()

    outcomes = classify_and_persist(messages, config, gateway, db_path=db_path)
    noise_count = sum(1 for o in outcomes if o.label == "noise")
    signal_count = len(outcomes) - noise_count
    print(f"Classified {len(outcomes)} message(s): {signal_count} signal, {noise_count} noise.")

    result = run_daily_digest_job(CHANNEL_ID, config, gateway, publisher, day=day, db_path=db_path)
    print(f"[run] {config.display_name} ({CHANNEL_ID}) {result.date}: {result.status} -- {result.detail}")

    if result.status == SKIPPED_NON_WORKING_DAY:
        print(f"  (skipping ledger build -- {result.date} is not a working day for this channel)")
    else:
        # Visibility only, not part of the scored production path -- see
        # run_live_pipeline_p1_agent_test.py's identical note.
        ledger_records = build_and_persist_ledger(CHANNEL_ID, date.fromisoformat(result.date), config, db_path=db_path)
        print(f"Persisted {len(ledger_records)} participation ledger row(s) for {result.date} "
              "(only non-responders are ever recorded -- see p1.participation.ledger's own docstring).")
    return result


def _parse_day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--day",
        default=None,
        help="Target a specific working day (YYYY-MM-DD) instead of today in the channel's own timezone.",
    )
    args = parser.parse_args()

    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not tenant_id or not client_id or not team_id:
        print("AZURE_TENANT_ID, AZURE_CLIENT_ID, and GRAPH_TEAM_ID must all be set in .env.")
        return 1

    # Refreshed silently from the MSAL token cache -- a static
    # GRAPH_ACCESS_TOKEN from .env is only valid ~75 minutes and produces
    # a 401 on any run after that. See run_live_pipeline_p1_agent_test.py
    # for the same fix and its full rationale.
    try:
        access_token = get_access_token(tenant_id=tenant_id, client_id=client_id, allow_interactive=False)
    except GraphAuthError as exc:
        print(f"Graph auth failed -- {exc}")
        return 1

    result = run_live_pipeline(access_token=access_token, team_id=team_id, day=_parse_day(args.day))
    return 0 if result.status != "rejected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
