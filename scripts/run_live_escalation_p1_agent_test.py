"""The real, live escalation test against the real p1-agent-test Teams
channel: read whatever the local db already knows about participation
and run p1.escalations.escalation_job against it, via the exact same
production function (run_escalation_job) every mock-fixture test
already exercises -- pointed at the real channel_id and a real
PowerAutomateTeamsPublisher instead of fixtures and a mock.

No new Graph ingestion here -- that is what
run_live_pipeline_p1_agent_test.py is for. This mirrors
run_live_nudge_p1_agent_test.py exactly (same "read local db, run the
real job body" shape); the one job type that had no one-shot live
script yet.

Escalation is per-member and streak-based, independent of whether that
person was ever nudged: a member only becomes a candidate once they
have config.escalation_threshold_days consecutive WORKING days (per
the real participation ledger) with no qualifying update, unbroken by
any day they did contribute or any day marked EXCLUDED. Like the daily
digest and nudges, the first-ever escalation for any person is left
PENDING for a human to approve; escalation is always a private message
to config.channel_owner_id, never a channel post.

Usage:
    uv run python scripts/run_live_escalation_p1_agent_test.py [--day YYYY-MM-DD]
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
from p1.escalations.escalation_job import run_escalation_job
from p1.storage.db import init_db

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test


def run_live_escalation(*, day: date | None = None, db_path: str = LIVE_DB_PATH, publisher=None):
    init_db(db_path)
    ChannelConfigStore().sync_to_db(db_path)

    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    publisher = publisher or get_teams_publisher()

    results = run_escalation_job(CHANNEL_ID, config, publisher, day=day, db_path=db_path)
    if not results:
        print(f"[escalation] {config.display_name} ({CHANNEL_ID}): no candidate reached "
              f"the {config.escalation_threshold_days}-day threshold for this day.")
    for r in results:
        print(f"[escalation] {config.display_name} ({CHANNEL_ID}) {r.date} {r.member_id}: {r.status} -- {r.detail}")
    return results


def _parse_day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--day",
        default=None,
        help="Target a specific day (YYYY-MM-DD, channel-local) instead of today.",
    )
    args = parser.parse_args()

    results = run_live_escalation(day=_parse_day(args.day))
    return 1 if any(r.status == "rejected" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
