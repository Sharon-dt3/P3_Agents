"""
Ad-hoc, one-off verification script (2026-09-20): generate today's
p1-agent-test daily summary on demand, against the real live gateway
and the real live database, WITHOUT going through daily_job.py's
publish/approval path at all -- this only calls
generate_and_persist_daily_summary() directly, the same function
CHN-17's scheduled job calls, so it writes/overwrites today's row in
the digests table (safe -- DigestStore.record() is designed to let a
not-yet-sent digest be regenerated) but creates no proposal and sends
nothing to Teams. Purpose: confirm, by reading the printed content,
whether today's more varied fact set (a question, a blocker, a
decision, and a status update, across four different sections) comes
back as genuinely reworded model prose rather than a near-verbatim
echo of the single-fact case from 2026-09-19.

Usage:
    uv run python scripts/test_digest_today_adhoc.py
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
from p1.reporting.daily_summary import generate_and_persist_daily_summary

CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"
LIVE_DB_PATH = "data/p1_live.db"


def main() -> int:
    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    gateway = LLMGateway()
    result = generate_and_persist_daily_summary(
        CHANNEL_ID, date.today(), config, gateway, db_path=LIVE_DB_PATH,
    )
    print("=" * 70)
    print(result.content)
    print("=" * 70)
    for section, failures in result.dropped.items():
        for f in failures:
            print(f"DROPPED [{section}]: {f.reason} -- {f.detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
