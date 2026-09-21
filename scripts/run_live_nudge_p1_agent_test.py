"""The real, live nudge test against the real p1-agent-test Teams
channel: read whatever the local db already knows about who has and
hasn't posted today (no new Graph ingestion here -- that is what
run_live_pipeline_p1_agent_test.py is for) and run p1.nudges.nudge_job
against it, via the exact same production function
(run_nudge_job) every mock-fixture test and the eval harness already
exercise -- pointed at the real channel_id and a real
PowerAutomateTeamsPublisher instead of fixtures and a mock.

Unlike the daily digest, nudges have never been triggered once on this
channel: NudgeStore.has_ever_been_nudged() is False for every roster
member, so the first nudge for a given person is always left PENDING
for a human to approve in the dashboard or via scripts/approve_cli.py
-- exactly the "real approval waiting for a decision" case the daily
digest can no longer produce here (see chat, 2026-09-20:
has_ever_published() already flipped True for this channel on 09-17,
so every digest since has auto-approved on creation).

Before running this for real:

1. config/channels/p1-agent-test.yaml must have nudge_enabled: true --
   it is false by default (OFF BY DEFAULT is nudge_job.py's own first
   guarantee). This script does not flip it for you.

2. A nudge only gets created for a roster member whose participation
   ledger state for the target day is NO_MESSAGE or POSTED_NO_UPDATE
   (not EXCLUDED). If nobody has posted anything qualifying today,
   every roster member who isn't on the exceptions list is eligible.

3. `--day` defaults to today in UTC, not the channel's own timezone --
   nudge_job.py has the same UTC-vs-local inconsistency daily_job.py
   used to have, not yet fixed (see chat). Pass --day explicitly
   (YYYY-MM-DD, channel-local) to be exact about which day you mean.

Usage:
    uv run python scripts/run_live_nudge_p1_agent_test.py [--day YYYY-MM-DD]
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
from p1.nudges.nudge_job import run_nudge_job
from p1.storage.db import init_db

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test


def run_live_nudge(*, day: date | None = None, db_path: str = LIVE_DB_PATH, publisher=None):
    init_db(db_path)
    # Same reason run_live_pipeline_p1_agent_test.py calls this: channels.id
    # is a foreign key nudges/proposals rows point at, and this also picks
    # up any YAML edit (like nudge_enabled: true) made since the db was
    # last synced.
    ChannelConfigStore().sync_to_db(db_path)

    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    publisher = publisher or get_teams_publisher()

    results = run_nudge_job(CHANNEL_ID, config, publisher, day=day, db_path=db_path)
    if not results:
        print(f"[nudge] {config.display_name} ({CHANNEL_ID}): no eligible non-responders for this day.")
    for r in results:
        who = r.member_id or "(channel-level)"
        print(f"[nudge] {config.display_name} ({CHANNEL_ID}) {r.date} {who}: {r.status} -- {r.detail}")
    return results


def _parse_day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--day",
        default=None,
        help="Target a specific day (YYYY-MM-DD, channel-local) instead of today in UTC (see caveat 3 above).",
    )
    args = parser.parse_args()

    results = run_live_nudge(day=_parse_day(args.day))
    # non-zero exit only on a genuine failure to even attempt anything --
    # awaiting_approval/cap_reached/excluded are all expected, valid outcomes.
    return 1 if any(r.status == "rejected" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
