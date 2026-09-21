"""
Ad-hoc, one-off verification script (2026-09-20): generate the
p1-agent-test weekly roll-up on demand, against the real live gateway
and the real live database, calling generate_and_persist_weekly_rollup()
directly -- the same function a real weekly schedule would call.
Writes/overwrites this week's row in the digests table (type='weekly';
safe to regenerate, same idempotency-key design as the daily digest)
but creates no proposal and sends nothing to Teams.

Purpose: unlike the daily digest (which just needed to confirm a real
call happens at all), this checks a real, falsifiable behavior --
WeeklyNarrativeDraft's own field_validator rejects any digit character
in the model's closing sentence and forces a retry, even though the
briefing block handed to the model DOES contain real numbers
(participation percentages, blocker/decision/question counts). A mock
or a pass-through would have no reason to avoid echoing those numbers;
a real, validated model call will not contain a single digit in the
narrative line, guaranteed by the retry loop, not just requested by
the prompt.

Usage:
    uv run python scripts/test_weekly_today_adhoc.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.config.loader import ChannelConfigStore
from p1.llm.gateway import LLMGateway
from p1.reporting.weekly_summary import generate_and_persist_weekly_rollup

CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"
LIVE_DB_PATH = "data/p1_live.db"


def main() -> int:
    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    gateway = LLMGateway()
    result = generate_and_persist_weekly_rollup(
        CHANNEL_ID, date.today(), config, gateway, db_path=LIVE_DB_PATH,
    )
    print("=" * 70)
    print(result.content)
    print("=" * 70)
    has_digit = any(ch.isdigit() for ch in result.narrative)
    print(f"narrative sentence: {result.narrative!r}")
    print(f"contains a digit? {has_digit}  (must be False -- the validator should have blocked it otherwise)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
