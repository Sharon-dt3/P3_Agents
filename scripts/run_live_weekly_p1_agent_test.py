"""The real, live weekly roll-up run for p1-agent-test: the same function
the live runner's Friday job calls (p1.publishing.weekly_job.run_weekly_rollup_job),
pointed at the real channel and the real Power Automate publisher.

Use it for the two things the once-a-week scheduler cannot do on its own:

  1. SEND THE FIRST ONE AFTER APPROVAL. The first weekly roll-up ever sent
     to a channel is held for a human (a weekly roll-up is a new kind of
     post for the channel). Run this once to create the pending proposal
     (nothing is sent -- expect status "awaiting_approval"), approve it
     (scripts/approve_cli.py or the approval dashboard), then run this
     again: it finds the approved proposal and sends it, exactly once.
  2. RETRY a failed run (e.g. a model timeout logged as "[weekly] FAILED").

Idempotent: safe to run any number of times for the same week. Once a
channel has had one weekly roll-up published, later weeks send unattended.

WARNING: once a proposal for the week is approved, running this posts to
the real Teams channel. Before that it only creates/refreshes the pending
proposal. For a read-only look at the content, use
scripts/demo_06_weekly_rollup.py instead.

Usage:
    uv run python scripts/run_live_weekly_p1_agent_test.py [--week-end YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.factory import get_teams_publisher
from p1.config.loader import ChannelConfigStore
from p1.llm.gateway import LLMGateway
from p1.publishing.weekly_job import run_weekly_rollup_job
from p1.storage.db import init_db

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--week-end", default=None,
        help="Last day of the week to summarise, YYYY-MM-DD (default: today in the channel's own timezone).",
    )
    args = parser.parse_args()

    init_db(LIVE_DB_PATH)
    ChannelConfigStore().sync_to_db(LIVE_DB_PATH)
    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)

    result = run_weekly_rollup_job(
        CHANNEL_ID, config, LLMGateway(), get_teams_publisher(),
        week_end=date.fromisoformat(args.week_end) if args.week_end else None,
        db_path=LIVE_DB_PATH,
    )
    print(f"[weekly] {config.display_name} week ending {result.date}: {result.status} -- {result.detail}")
    return 1 if result.status == "rejected" else 0


if __name__ == "__main__":
    raise SystemExit(main())
