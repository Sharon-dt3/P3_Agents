"""
Live Graph smoke test (CHN-01's acceptance test): a small, deliberately
read-only script that proves GraphTeamsReader can actually talk to a
real Microsoft tenant, before trusting it anywhere near the real
pipeline (ingestion, detection, digests, nudges -- none of that is
touched here).

Requires GRAPH_ACCESS_TOKEN (from scripts/graph_login.py) and
GRAPH_TEAM_ID (the Team's M365 Group ID -- the `groupId` query
parameter in a channel's "Get link to channel" URL) in .env. Does not
require or check TEAMS_READER_MODE -- this script always talks to
Graph directly, regardless of that setting, since its whole point is
to test the live connection in isolation from the rest of the app.

Usage:
    uv run python scripts/graph_smoke_test.py

Prints the real channels this token can see for the configured team,
then -- only for a channel_id also present in this repo's own
allowlist (config/channels/*.yaml, allowlisted: true) -- fetches one
page of real messages and prints a short, redacted preview of each
(author and timestamp only, never full message text, so nothing here
ends up echoed into a terminal transcript or a recording by accident).
A channel that Graph can see but that isn't on the allowlist is named
but not read, the same allow-by-default-refuse rule CHN-04's scope
gate enforces everywhere else in this codebase -- this script never
bypasses it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.loader import ChannelConfigStore


def run_smoke_test(*, access_token: str, team_id: str, reader_factory=GraphTeamsReader) -> int:
    """reader_factory is a seam for tests: production always builds the
    real GraphTeamsReader (the default), tests substitute a fake one
    that never opens a real network connection."""
    reader = reader_factory(access_token=access_token, team_id=team_id)

    print(f"Connecting to team {team_id} ...")
    channels = reader.list_channels()
    if not channels:
        print("Connected, but Graph returned zero channels for this team/token.")
        return 0

    print(f"Graph can see {len(channels)} channel(s) on this team:")
    for channel in channels:
        print(f"  {channel.id}  --  {channel.display_name}")

    allowlisted_ids = set(ChannelConfigStore().list_allowlisted_channels())
    readable = [c for c in channels if c.id in allowlisted_ids]
    if not readable:
        print("\nNone of these channel_ids are on this repo's allowlist yet -- add one to "
              "config/channels/*.yaml (allowlisted: true) to read real messages from it.")
        return 0

    target = readable[0]
    print(f"\n{target.id} is allowlisted -- fetching one page of real messages:")
    page = reader.list_messages(target.id)
    if not page.messages:
        print("  (connected fine, zero messages returned)")
    for message in page.messages[:10]:
        print(f"  {message.author_id}  {message.posted_at}")
    print(f"\nLive Graph connection confirmed for {target.id}.")
    return 0


def main() -> int:
    access_token = os.environ.get("GRAPH_ACCESS_TOKEN")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not access_token or not team_id:
        print("GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID must both be set in .env -- run "
              "scripts/graph_login.py first, and set GRAPH_TEAM_ID from a channel's "
              "\"Get link to channel\" URL (its groupId query parameter).")
        return 1
    return run_smoke_test(access_token=access_token, team_id=team_id)


if __name__ == "__main__":
    raise SystemExit(main())
