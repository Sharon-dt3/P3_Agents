"""
Safe test of the real p1-agent-test pipeline: real Graph token refresh,
real ingest, real classification -- then STOPS. Never calls
run_daily_digest_job, never creates a proposal, never touches a
publisher. This is the "why did that message actually appear on Teams"
lesson from 2026-09-23 turned into a script: run_live_pipeline_*.py's
own ingest/classify steps have real, wanted side effects (new messages
and their classifications land in data/p1_live.db, exactly what you'd
want before trusting a digest preview) -- it was only the run_daily_digest_job
call after them that could reach a live Teams channel. This script
reuses the exact same ingest/classify code (build_scoped_reader,
_load_channel_messages from run_live_pipeline_p1_agent_test.py) so the
data it leaves behind is identical to what a real run would produce,
then reports today's digest content read-only via generate_daily_summary
-- the same function scripts/preview_daily_summary_p1_agent_test.py
uses -- instead of run_daily_digest_job.

Nothing in this script can ever post to Teams. If you want the real
send too, run scripts/run_live_pipeline_p1_agent_test.py instead --
deliberately a separate, differently-named script so the two are never
confused at the command line.

Usage:
    uv run python scripts/dry_run_pipeline_p1_agent_test.py [--day YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.graph_auth import GraphAuthError, get_access_token
from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.ingestion.sync import sync_channel
from p1.llm.gateway import LLMGateway
from p1.reporting.daily_summary import generate_daily_summary
from p1.storage.db import init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

# Reuses the real run_live_pipeline_p1_agent_test.py's own helpers rather
# than re-implementing scoped-reader construction or message reload --
# see that module for what each one does.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_live_pipeline_p1_agent_test import CHANNEL_ID, _load_channel_messages, build_scoped_reader

LIVE_DB_PATH = "data/p1_live.db"


def _parse_day(value: str | None, timezone: str) -> date:
    if value:
        return date.fromisoformat(value)
    return __import__("datetime").datetime.now(ZoneInfo(timezone)).date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--day",
        default=None,
        help="Calendar day (YYYY-MM-DD, channel-local) to preview. Defaults to today.",
    )
    args = parser.parse_args()

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
    ChannelConfigStore().sync_to_db(LIVE_DB_PATH)

    reader = build_scoped_reader(
        access_token=access_token, team_id=team_id, db_path=LIVE_DB_PATH, reader_factory=GraphTeamsReader,
    )
    sync_result = sync_channel(reader, CHANNEL_ID, SyncStateStore(LIVE_DB_PATH), MessageStore(LIVE_DB_PATH))
    resynced_note = " (resynced from scratch)" if sync_result.resynced else ""
    print(f"Ingested {sync_result.messages_ingested} new message(s){resynced_note}.")

    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    messages = _load_channel_messages(LIVE_DB_PATH, CHANNEL_ID)
    print(f"{len(messages)} total non-deleted message(s) known for this channel.")

    gateway = LLMGateway()
    outcomes = classify_and_persist(messages, config, gateway, db_path=LIVE_DB_PATH)
    noise_count = sum(1 for o in outcomes if o.label == "noise")
    print(f"Classified {len(outcomes)} message(s) total in this channel's history: "
          f"{len(outcomes) - noise_count} non-noise, {noise_count} noise "
          "(this is every stored message, not just today's -- see today's breakdown below).")

    day = _parse_day(args.day, config.timezone)
    print()
    print(f"--- Read-only preview of {config.display_name}'s digest for {day.isoformat()} "
          f"({config.timezone}) -- nothing sent, nothing published ---")
    print()
    result = generate_daily_summary(CHANNEL_ID, day, config, gateway, db_path=LIVE_DB_PATH)
    print(result.content)

    any_dropped = False
    for section, failures in result.dropped.items():
        if failures:
            any_dropped = True
            print(f"[dropped from '{section}' by the grounding kernel]")
            for f in failures:
                print(f"  {f}")
    if not any_dropped:
        print("(no lines were dropped by the grounding kernel)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
