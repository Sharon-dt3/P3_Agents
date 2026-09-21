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

Reads the channel(s) to test directly from this repo's own allowlist
(config/channels/*.yaml, allowlisted: true) rather than asking Graph to
enumerate every channel on the team first. That's a deliberate choice,
not a shortcut: Graph's "list channels" call needs its own permission
(Channel.ReadBasic.All) on top of ChannelMessage.Read.All, which this
tenant's admin-consent process makes expensive to add (see
DECISION_LOG.md's CHN-01 follow-up) -- and config already knows which
channel_ids are in scope, so there's nothing Graph's enumeration would
tell us that we don't already have. The tradeoff: this script can no
longer show you every channel Graph can see on the team, so if you need
a new real channel_id, get it the same way GRAPH_TEAM_ID was
obtained -- open the channel in Teams, "Get link to channel", and read
the id out of the URL (the segment starting "19:" and ending
"@thread.tacv2", url-decoded) -- and add it to a
config/channels/*.yaml file with allowlisted: true before running this.

Usage:
    uv run python scripts/graph_smoke_test.py

For each allowlisted channel_id already in config/channels/*.yaml,
fetches one page of real messages and prints a short, redacted preview
of each (author and timestamp only, never full message text, so
nothing here ends up echoed into a terminal transcript or a recording
by accident). A channel_id Graph rejects (wrong team, typo, or a
mock-fixture id like "proj-alpha" that was never a real Graph id) is
reported as such, not silently skipped.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

import httpx

from p1.adapters.teams_reader import DeltaTokenExpiredError
from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.loader import ChannelConfigStore


def run_smoke_test(
    *, access_token: str, team_id: str, reader_factory=GraphTeamsReader, config_store=None,
) -> int:
    """reader_factory and config_store are seams for tests: production
    always builds the real GraphTeamsReader and reads this repo's real
    config/channels/*.yaml (both defaults), tests substitute a fake
    reader and a temp-dir-backed ChannelConfigStore so nothing here
    ever opens a real network connection or depends on the repo's
    actual committed channel configs."""
    reader = reader_factory(access_token=access_token, team_id=team_id)
    config_store = config_store or ChannelConfigStore()

    allowlisted_ids = config_store.list_allowlisted_channels()
    if not allowlisted_ids:
        print("No channels are allowlisted in config/channels/*.yaml yet -- add one "
              "(allowlisted: true) with a real channel_id from Teams' own \"Get link "
              "to channel\" URL before running this smoke test.")
        return 0

    print(f"Connecting to team {team_id} ...")
    any_confirmed = False
    for channel_id in allowlisted_ids:
        print(f"\n{channel_id} is allowlisted -- fetching one page of real messages:")
        try:
            page = reader.list_messages(channel_id)
        except (httpx.HTTPStatusError, DeltaTokenExpiredError) as exc:
            # Both mean the same thing here: Graph didn't accept this
            # channel_id on this team. GraphTeamsReader.list_messages()
            # turns a bare 410 into DeltaTokenExpiredError before checking
            # for any other error status -- Graph returns 410 (not 404) for
            # some ids it can't resolve at all, not only for a genuinely
            # expired delta token, so this script treats the two the same:
            # reported, and move on to the next channel, never a crash.
            print(f"  Graph rejected this channel_id: {exc}")
            print("  (a mock-fixture id like \"19:proj-alpha@thread.tacv2\" was never a "
                  "real Graph id -- swap in a real one from Teams' \"Get link to channel\" URL)")
            continue
        any_confirmed = True
        if not page.messages:
            print("  (connected fine, zero messages returned)")
        for message in page.messages[:10]:
            print(f"  {message.author_id}  {message.posted_at}")
        print(f"  Live Graph connection confirmed for {channel_id}.")

    return 0 if any_confirmed else 1


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
