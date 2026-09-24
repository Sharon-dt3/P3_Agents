"""
Recording beat 6 (CHN-32): the weekly roll-up for the real p1-agent-test
channel, generated live by the real production function
(p1.reporting.weekly_summary.generate_weekly_rollup) against the real
database and real model.

Read-only: uses generate_weekly_rollup, NOT the generate_and_persist
variant scripts/test_weekly_today_adhoc.py calls, so nothing is written to
the digests table and nothing is sent to Teams. Every number in the roll-up
(participation, blocker/decision/question counts) is computed in code; the
model only writes the one closing narrative sentence, and a validator
rejects any digit in it, so the model cannot restate or alter a figure.

The week runs up to --end (default: today, in the channel's own timezone),
so running it before Friday previews the week so far.

Usage:
    uv run python scripts/demo_06_weekly_rollup.py                  # p1-agent-test
    uv run python scripts/demo_06_weekly_rollup.py --channel teams  # Teams-agent-test
    uv run python scripts/demo_06_weekly_rollup.py --end 2026-09-25
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
from p1.reporting.weekly_summary import generate_weekly_rollup

CHANNELS = {
    "p1": "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2",  # p1-agent-test
    "teams": "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2",  # Teams-agent-test
}
LIVE_DB_PATH = "data/p1_live.db"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", default=None, help="last day of the week to summarise, YYYY-MM-DD (default: today)")
    parser.add_argument("--channel", choices=sorted(CHANNELS), default="p1")
    args = parser.parse_args()

    channel_id = CHANNELS[args.channel]
    config = ChannelConfigStore().get_channel_config(channel_id)
    end = date.fromisoformat(args.end) if args.end else datetime.now(ZoneInfo(config.timezone)).date()
    gateway = LLMGateway()

    print("=" * 78)
    print(f"{config.display_name}: weekly roll-up for the week ending {end.isoformat()} "
          f"(scheduled {config.weekly_digest_day} {config.weekly_digest_time.strftime('%H:%M')} {config.timezone})")
    print(f"model: {gateway.ollama_model}  |  read-only, nothing saved or sent")
    print("=" * 78)

    result = generate_weekly_rollup(channel_id, end, config, gateway, db_path=LIVE_DB_PATH)
    print(result.content)
    print("=" * 78)
    print(f"model-written narrative sentence: {result.narrative!r}")
    print(f"contains a digit? {any(ch.isdigit() for ch in result.narrative)}  (must be False -- figures are computed in code, never by the model)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
