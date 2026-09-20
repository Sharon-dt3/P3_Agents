"""
2026-09-19 recovery script: the real 2026-09-19 p1-agent-test digest
(the one containing the two genuine "Finished the API integration..."
and "Finished wiring the P1 live pipeline..." updates) was approved and
marked `applied` through app/approval_dashboard.py *before* that
dashboard's missing load_dotenv() call was found and fixed -- so it
silently went to the mock LogPublisher (data/outbound_log.jsonl)
instead of the real Teams channel. See DECISION_LOG.md's "the approval
dashboard never loaded .env" entry.

An `applied` proposal is a permanent, terminal state by design
(SPN-08's own guarantee: a decided proposal is never re-sent through
the normal guarded_send()/approve_and_send() path, which is exactly
what stops a digest from ever being posted twice). This script does
NOT go through that path at all -- same pattern as
scripts/power_automate_smoke_test.py: a human runs this once, on
purpose, to manually recover one specific real proposal's real content
that never reached its intended destination, calling
PowerAutomateTeamsPublisher directly. It is not a general "resend any
proposal" tool and takes no idempotency_key argument other than the
one hardcoded default below -- reuse for a different proposal should
be a deliberate, separate decision, not a flag flip.

The message posted is prefixed with a visible "[Recovered digest]"
disclosure line naming the real reason and the original date, so
nobody reading the real channel is misled into thinking this posted on
2026-09-19 itself.

Usage:
    uv run python scripts/repost_stuck_digest.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.teams_publisher_power_automate import (
    PowerAutomatePublishError,
    PowerAutomateTeamsPublisher,
)

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"
IDEMPOTENCY_KEY = f"{CHANNEL_ID}:2026-09-19:daily_publish"


def _load_real_content(db_path: str, idempotency_key: str) -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT payload, status FROM proposals WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise SystemExit(f"No proposal found for idempotency_key={idempotency_key!r}")
    if row["status"] != "applied":
        raise SystemExit(
            f"Proposal for {idempotency_key!r} has status {row['status']!r}, not 'applied' -- "
            "refusing to repost something that was never actually approved."
        )
    return json.loads(row["payload"])["content"]


def main() -> int:
    flow_url = os.environ.get("POWER_AUTOMATE_FLOW_URL")
    if not flow_url:
        print("POWER_AUTOMATE_FLOW_URL must be set in .env.")
        return 1

    real_content = _load_real_content(LIVE_DB_PATH, IDEMPOTENCY_KEY)
    message = (
        "[Recovered digest -- originally generated and approved 2026-09-19, "
        "but silently sent to a local mock log instead of Teams due to a bug "
        "in the approval dashboard, fixed the same day. Reposted manually, "
        "once, to deliver the real content below.]\n\n" + real_content
    )

    publisher = PowerAutomateTeamsPublisher(flow_url=flow_url)
    try:
        result = publisher.post_channel_message(CHANNEL_ID, message)
    except PowerAutomatePublishError as exc:
        print(f"Power Automate flow rejected the post: {exc}")
        return 1

    print(f"Reposted the real 2026-09-19 digest to {CHANNEL_ID} via the Power Automate flow.")
    print(f"Flow response: {result!r}")
    print("Check the real p1-agent-test channel in Teams to confirm it landed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
