"""
Live Graph replies smoke test -- a companion to graph_smoke_test.py,
proving GraphTeamsReader.list_replies() specifically. list_messages()
only ever returns a channel's top-level posts (Graph's own API shape,
not a limitation this codebase added) -- a thread reply never shows up
there, however long you wait after posting one. This script calls the
one thing that actually returns replies: list_replies(parent_message_id),
for every top-level message currently in an allowlisted channel.

Deliberately read-only, same redaction discipline as graph_smoke_test.py
(author, timestamp, edited_at -- never the message body), so nothing
here ends up echoed into a terminal transcript or a recording by
accident.

Requires GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID in .env, same as
graph_smoke_test.py -- run scripts/graph_login.py first if needed.

Usage:
    uv run python scripts/graph_replies_smoke_test.py
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


def run_replies_smoke_test(
    *, access_token: str, team_id: str, reader_factory=GraphTeamsReader, config_store=None,
) -> int:
    reader = reader_factory(access_token=access_token, team_id=team_id)
    config_store = config_store or ChannelConfigStore()

    allowlisted_ids = config_store.list_allowlisted_channels()
    if not allowlisted_ids:
        print("No channels are allowlisted in config/channels/*.yaml yet.")
        return 0

    print(f"Connecting to team {team_id} ...")
    any_confirmed = False
    for channel_id in allowlisted_ids:
        print(f"\n{channel_id} is allowlisted -- fetching top-level messages first "
              "(list_replies needs this to resolve which channel a message_id belongs to):")
        try:
            page = reader.list_messages(channel_id)
        except (httpx.HTTPStatusError, DeltaTokenExpiredError) as exc:
            print(f"  Graph rejected this channel_id: {exc}")
            continue

        if not page.messages:
            print("  (connected fine, zero top-level messages returned)")
            continue

        for message in page.messages[:10]:
            print(f"\n  Checking replies to message {message.id}  "
                  f"(posted {message.posted_at}, edited_at={message.edited_at}) ...")
            replies = reader.list_replies(message.id)
            any_confirmed = True
            if not replies:
                print("    (no replies on this message)")
                continue
            for reply in replies:
                print(f"    reply {reply.id}  author={reply.author_id}  "
                      f"posted={reply.posted_at}  edited_at={reply.edited_at}  "
                      f"thread_root_id={reply.thread_root_id}")

    return 0 if any_confirmed else 1


def main() -> int:
    access_token = os.environ.get("GRAPH_ACCESS_TOKEN")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not access_token or not team_id:
        print("GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID must both be set in .env -- run "
              "scripts/graph_login.py first.")
        return 1
    return run_replies_smoke_test(access_token=access_token, team_id=team_id)


if __name__ == "__main__":
    raise SystemExit(main())
