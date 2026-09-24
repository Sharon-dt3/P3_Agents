"""
"What will the daily summary say at 17:30?" -- a fast, read-only-to-Teams
preview for either real channel.

Runs the same steps the scheduled digest job depends on, right now:
  1. ingest the latest messages from Graph (through the real scope gate)
  2. classify TODAY's messages only (rules first, then the model) -- the
     same classify_and_persist the live runners use, so the labels it
     writes are the labels the real 17:30 digest will see
  3. show every message from today: when it was posted, its label, and
     WHAT decided it (a named rule, or the model with its confidence)
  4. generate the digest with the real generate_daily_summary and print
     it exactly as it would be posted

Never posts anything and never creates a proposal. Writing ingested
messages and classifications into data/p1_live.db is the same thing the
live runners already do every 5 minutes. The digest's prose is written by
the model, so wording can differ slightly between this preview and the
real 17:30 run if messages change or the model phrases things differently.

Usage:
    uv run python scripts/preview_digest_now.py                  # p1-agent-test
    uv run python scripts/preview_digest_now.py --channel teams  # Teams-agent-test
    uv run python scripts/preview_digest_now.py --no-ingest      # skip the Graph pull
    uv run python scripts/preview_digest_now.py --day 2026-09-23 # another day
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.graph_auth import GraphAuthError, get_access_token
from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.calendar import to_local
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.governance.scope_gate import ScopedTeamsReader
from p1.ingestion.sync import sync_channel
from p1.llm.gateway import LLMGateway
from p1.participation.ledger import NonWorkingDayError
from p1.reporting.daily_summary import generate_daily_summary
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore
from run_live_pipeline_p1_agent_test import _load_channel_messages

LIVE_DB_PATH = "data/p1_live.db"
CHANNELS = {
    "p1": "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2",  # p1-agent-test
    "teams": "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2",  # Teams-agent-test
}


def _plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _already_published(channel_id: str, day: date) -> str | None:
    conn = get_connection(LIVE_DB_PATH)
    try:
        row = conn.execute(
            "SELECT published_at FROM digests WHERE channel_id = ? AND date = ? AND type = 'daily'",
            (channel_id, day.isoformat()),
        ).fetchone()
    finally:
        conn.close()
    return row["published_at"] if row and row["published_at"] else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--channel", choices=sorted(CHANNELS), default="p1")
    parser.add_argument("--day", default=None, help="YYYY-MM-DD in the channel's own timezone (default: today)")
    parser.add_argument("--no-ingest", action="store_true", help="skip the Graph pull, use what is already stored")
    args = parser.parse_args()

    channel_id = CHANNELS[args.channel]
    config = ChannelConfigStore().get_channel_config(channel_id)
    tz = ZoneInfo(config.timezone)
    now = datetime.now(tz)
    day = date.fromisoformat(args.day) if args.day else now.date()

    digest_at = datetime.combine(day, config.daily_digest_time, tzinfo=tz)
    minutes = int((digest_at - now).total_seconds() // 60)
    when = f"in {minutes} min" if minutes > 0 else f"{-minutes} min ago"

    print("=" * 78)
    print(f"{config.display_name}  |  digest for {day.isoformat()}  |  window "
          f"{config.update_window_start.strftime('%H:%M')}-{config.update_window_end.strftime('%H:%M')} {config.timezone}")
    print(f"now {now.strftime('%H:%M')}  |  daily digest is scheduled for {digest_at.strftime('%H:%M')} ({when})")
    published_at = _already_published(channel_id, day)
    if published_at:
        print(f"NOTE: a digest for this day was already published at {published_at} -- the 17:30 job will not post a second one.")
    print("=" * 78)

    init_db(LIVE_DB_PATH)

    if not args.no_ingest:
        tenant_id, client_id, team_id = (os.environ.get(k) for k in ("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "GRAPH_TEAM_ID"))
        if not tenant_id or not client_id or not team_id:
            print("AZURE_TENANT_ID, AZURE_CLIENT_ID, and GRAPH_TEAM_ID must all be set in .env.")
            return 1
        try:
            token = get_access_token(tenant_id=tenant_id, client_id=client_id, allow_interactive=False)
        except GraphAuthError as exc:
            print(f"Graph auth failed -- {exc}")
            return 1
        gate = ScopedTeamsReader(
            GraphTeamsReader(access_token=token, team_id=team_id),
            allowlisted_channel_ids=[channel_id], db_path=LIVE_DB_PATH,
        )
        result = sync_channel(gate, channel_id, SyncStateStore(LIVE_DB_PATH), MessageStore(LIVE_DB_PATH))
        print(f"Ingested {result.messages_ingested} new message(s) from Teams.")

    todays = [m for m in _load_channel_messages(LIVE_DB_PATH, channel_id) if to_local(m.posted_at, config.timezone).date() == day]
    gateway = LLMGateway()
    print(f"Classifying {len(todays)} message(s) from {day.isoformat()} with model {gateway.ollama_model} ...")
    outcomes = {o.message_id: o for o in classify_and_persist(todays, config, gateway, db_path=LIVE_DB_PATH)}

    print()
    print("Today's messages and what decided each one:")
    if not todays:
        print("   (none yet)")
    for m in sorted(todays, key=lambda x: x.posted_at):
        o = outcomes[m.id]
        decided = f"rule: {o.rule_name}" if o.method == "rule" else f"model ({o.confidence})"
        local = to_local(m.posted_at, config.timezone).strftime("%H:%M")
        print(f"   {local}  {o.label:<9} {decided:<30} {_plain(m.body)[:60]}")

    print()
    print("-" * 78)
    print(f"THE DIGEST AS IT WOULD BE POSTED AT {digest_at.strftime('%H:%M')} (right now, nothing sent):")
    print("-" * 78)
    try:
        summary = generate_daily_summary(channel_id, day, config, gateway, db_path=LIVE_DB_PATH)
    except NonWorkingDayError as exc:
        print(f"No digest: {exc}")
        return 0
    print(summary.content)
    for section, failures in summary.dropped.items():
        for f in failures:
            print(f"[grounding dropped a line from '{section}': {f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
