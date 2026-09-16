"""
Adapter factory (CHN-03/CHN-04): chooses the mock or real Teams reader
purely from config -- agent code never imports a concrete adapter
class -- and always returns it wrapped in the scope gate, so there is
no code path in this application that can obtain an ungated reader.
"""

from __future__ import annotations

import os

from p1.adapters.teams_reader import TeamsReader
from p1.adapters.teams_reader_mock import MockTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.governance.scope_gate import ScopedTeamsReader


def get_teams_reader() -> TeamsReader:
    mode = os.environ.get("TEAMS_READER_MODE", "mock")

    if mode == "mock":
        reader: TeamsReader = MockTeamsReader.from_fixtures()
    elif mode == "graph":
        from p1.adapters.teams_reader_graph import GraphTeamsReader

        access_token = os.environ.get("GRAPH_ACCESS_TOKEN")
        team_id = os.environ.get("GRAPH_TEAM_ID")
        if not access_token or not team_id:
            raise RuntimeError("TEAMS_READER_MODE=graph requires GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID")
        reader = GraphTeamsReader(access_token=access_token, team_id=team_id)
    else:
        raise ValueError(f"Unknown TEAMS_READER_MODE: {mode!r}")

    allowlisted_channel_ids = ChannelConfigStore().list_allowlisted_channels()
    return ScopedTeamsReader(reader, allowlisted_channel_ids)
