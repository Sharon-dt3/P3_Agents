"""
Adapter factory (CHN-03): chooses the mock or real Teams reader purely
from config -- agent code never imports a concrete adapter class.
"""

from __future__ import annotations

import os

from p1.adapters.teams_reader import TeamsReader
from p1.adapters.teams_reader_mock import MockTeamsReader


def get_teams_reader() -> TeamsReader:
    mode = os.environ.get("TEAMS_READER_MODE", "mock")

    if mode == "mock":
        return MockTeamsReader.from_fixtures()

    if mode == "graph":
        from p1.adapters.teams_reader_graph import GraphTeamsReader

        access_token = os.environ.get("GRAPH_ACCESS_TOKEN")
        team_id = os.environ.get("GRAPH_TEAM_ID")
        if not access_token or not team_id:
            raise RuntimeError("TEAMS_READER_MODE=graph requires GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID")
        return GraphTeamsReader(access_token=access_token, team_id=team_id)

    raise ValueError(f"Unknown TEAMS_READER_MODE: {mode!r}")
