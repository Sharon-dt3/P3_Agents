"""CHN-18 (golden case 6), run for real against p1-agent-test: run the
daily digest job three times over the same day and confirm exactly one
digest exists and the write log shows the suppressed attempts.

Deliberately skips Graph ingestion (that's what
run_live_pipeline_p1_agent_test.py is for) -- this only re-runs
run_daily_digest_job against whatever the local db already knows, so a
short-lived or expired GRAPH_ACCESS_TOKEN doesn't block it. For a day
with no messages this also never calls the LLM gateway at all --
daily_summary.py's own docstring: "when a section's fact list is
empty, _generate_section_lines returns immediately without ever
calling the model" -- so this is safe to run even with no reachable
model backend.

Usage:
    uv run python scripts/test_publish_idempotency_p1_agent_test.py --day 2026-09-20
    uv run python scripts/test_publish_idempotency_p1_agent_test.py --day 2026-09-20 --times 5
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.factory import get_teams_publisher
from p1.config.loader import ChannelConfigStore
from p1.llm.gateway import LLMGateway
from p1.publishing.daily_job import run_daily_digest_job
from p1.storage.db import init_db

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--day", required=True, help="YYYY-MM-DD, channel-local")
    parser.add_argument("--times", type=int, default=3, help="how many times to call the job (default 3)")
    parser.add_argument("--db-path", default=LIVE_DB_PATH)
    args = parser.parse_args()

    day = date.fromisoformat(args.day)
    db_path = args.db_path

    init_db(db_path)
    ChannelConfigStore().sync_to_db(db_path)
    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    gateway = LLMGateway()
    publisher = get_teams_publisher()

    for i in range(1, args.times + 1):
        result = run_daily_digest_job(CHANNEL_ID, config, gateway, publisher, day=day, db_path=db_path)
        print(f"run {i}/{args.times}: {result.status} -- {result.detail}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
