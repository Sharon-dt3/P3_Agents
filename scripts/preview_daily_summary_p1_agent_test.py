"""
Read-only preview of the real daily digest for p1-agent-test --
proves what run_daily_digest_job's own content generation will produce
for a given day WITHOUT any of the side effects that function has.

Calls p1.reporting.daily_summary.generate_daily_summary() directly --
the exact same fact-gathering (gather_daily_facts) and real model calls
(LLMGateway, same Ollama backend production uses) run_daily_digest_job
itself calls internally -- but stops one function short of
generate_and_persist_daily_summary(). Nothing here writes to the
digests table, creates or refreshes a proposal, or ever calls a
publisher. Running this script any number of times, for any day, has
zero effect on what the real scheduled cron does later.

Mirrors scripts/preview_daily_summary_teams_agent_test.py exactly,
pointed at p1-agent-test's own channel_id and timezone (Asia/Colombo)
instead of Teams-agent-test's.

Usage:
    uv run python scripts/preview_daily_summary_p1_agent_test.py --day 2026-09-22
    uv run python scripts/preview_daily_summary_p1_agent_test.py   # defaults to today, in the channel's own timezone
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.config.loader import ChannelConfigStore
from p1.llm.gateway import LLMGateway
from p1.reporting.daily_summary import generate_daily_summary

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test


def _parse_day(value: str | None, timezone: str) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(ZoneInfo(timezone)).date()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--day",
        default=None,
        help="Calendar day (YYYY-MM-DD, in the channel's own local timezone) to preview. "
        "Defaults to today in that timezone -- the same default run_daily_digest_job itself uses.",
    )
    args = parser.parse_args()

    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    day = _parse_day(args.day, config.timezone)

    print(f"Previewing {config.display_name} ({CHANNEL_ID})'s digest for {day.isoformat()} "
          f"({config.timezone}) -- read-only, nothing is written or sent.")
    print()

    gateway = LLMGateway()
    result = generate_daily_summary(CHANNEL_ID, day, config, gateway, db_path=LIVE_DB_PATH)

    print(result.content)
    print()

    any_dropped = False
    for section, failures in result.dropped.items():
        if failures:
            any_dropped = True
            print(f"[dropped from '{section}' by the grounding kernel -- see p1.grounding.kernel]")
            for f in failures:
                print(f"  {f}")
    if not any_dropped:
        print("(no lines were dropped by the grounding kernel)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
