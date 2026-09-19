"""
CHN-22's first real, live write: posts one obvious, clearly-labelled
test message into the real p1-agent-test Teams channel through the
actual PowerAutomateTeamsPublisher, over the real Power Automate flow
("P1 Teams Publisher") provisioned in make.powerautomate.com this
session -- confirming the write side end to end (this script -> the
flow's HTTP trigger -> its Condition -> Teams' "Post message in a chat
or channel" action -> the real channel) before anything in the
programme (the daily digest job, in particular) is trusted to post for
real. Same "prove it live with a dedicated, disclosed script before
anything production-shaped depends on it" pattern as
scripts/graph_smoke_test.py and scripts/run_live_ingest_p1_agent_test.py
used for the read side.

Deliberately calls PowerAutomateTeamsPublisher directly rather than
going through SPN-09's guarded_send() -- this script IS the guard here
(a human runs it, once, on purpose), the same way graph_smoke_test.py
calls GraphTeamsReader.list_messages() directly rather than going
through the full ingestion pipeline.

Requires POWER_AUTOMATE_FLOW_URL in .env (this session wrote it after
building and saving the flow; TEAMS_PUBLISHER_MODE=power_automate was
written alongside it so get_teams_publisher() also picks it up, but
this script talks to PowerAutomateTeamsPublisher directly so it works
even before that switch is flipped for the rest of the programme).

Usage:
    uv run python scripts/power_automate_smoke_test.py
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.teams_publisher_power_automate import (
    PowerAutomatePublishError,
    PowerAutomateTeamsPublisher,
)

# config/channels/p1-agent-test.yaml's real channel_id -- the same one
# scripts/run_live_ingest_p1_agent_test.py already proved live on the
# read side.
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"


def run_smoke_test(*, flow_url: str, publisher_factory=PowerAutomateTeamsPublisher) -> int:
    """publisher_factory is a seam for tests: production always builds
    the real PowerAutomateTeamsPublisher (the default), tests substitute
    a fake one that never opens a real network connection."""
    publisher = publisher_factory(flow_url=flow_url)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    message = (
        f"[P1 smoke test -- {stamp}] This is an automated connectivity check from "
        "scripts/power_automate_smoke_test.py. No action needed."
    )

    try:
        result = publisher.post_channel_message(CHANNEL_ID, message)
    except PowerAutomatePublishError as exc:
        print(f"Power Automate flow rejected the post: {exc}")
        return 1

    print(f"Posted a test message to {CHANNEL_ID} via the Power Automate flow.")
    print(f"Flow response: {result!r}")
    print("Check the real p1-agent-test channel in Teams to confirm it landed.")
    return 0


def main() -> int:
    flow_url = os.environ.get("POWER_AUTOMATE_FLOW_URL")
    if not flow_url:
        print("POWER_AUTOMATE_FLOW_URL must be set in .env -- see .env.example.")
        return 1
    return run_smoke_test(flow_url=flow_url)


if __name__ == "__main__":
    raise SystemExit(main())
