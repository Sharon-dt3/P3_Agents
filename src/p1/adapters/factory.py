"""
Adapter factory (CHN-03/CHN-04, CHN-22): chooses the mock or real Teams
reader/publisher purely from config -- agent code never imports a
concrete adapter class -- and always returns the reader wrapped in the
scope gate, so there is no code path in this application that can
obtain an ungated reader.

get_teams_publisher() deliberately has no equivalent scope-gate wrapper:
the read side's ScopedTeamsReader restricts WHICH channels a reader may
even see, but every write this programme ever makes already goes
through SPN-09's guarded_send() first, at the call site, not inside the
adapter -- adding a second, adapter-level gate here would duplicate
that check rather than add a new guarantee. See DECISION_LOG.md.
"""

from __future__ import annotations

import os

from p1.adapters.teams_publisher import TeamsPublisher
from p1.adapters.teams_publisher_mock import DEFAULT_LOG_PATH, LogPublisher
from p1.adapters.teams_reader import TeamsReader
from p1.adapters.teams_reader_mock import MockTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.governance.scope_gate import ScopedTeamsReader
from p1.storage.db import DEFAULT_DB_PATH


def get_teams_reader(db_path: str = DEFAULT_DB_PATH) -> TeamsReader:
    """db_path defaults to DEFAULT_DB_PATH (production behaviour, unchanged
    for every existing caller that passes nothing) but must be threaded
    through explicitly by any caller -- like scripts/run_walkthrough.py --
    that was itself given a different db_path, since ScopedTeamsReader
    writes audit rows to whatever db_path it is constructed with, not
    to whatever db the rest of that caller's flow happens to be using."""
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
    return ScopedTeamsReader(reader, allowlisted_channel_ids, db_path=db_path)


def get_teams_publisher() -> TeamsPublisher:
    mode = os.environ.get("TEAMS_PUBLISHER_MODE", "mock")

    if mode == "mock":
        log_path = os.environ.get("TEAMS_PUBLISHER_LOG_PATH", str(DEFAULT_LOG_PATH))
        return LogPublisher(log_path=log_path)
    if mode == "power_automate":
        from p1.adapters.teams_publisher_power_automate import (
            PowerAutomateTeamsPublisher,
        )

        flow_url = os.environ.get("POWER_AUTOMATE_FLOW_URL")
        if not flow_url:
            raise RuntimeError("TEAMS_PUBLISHER_MODE=power_automate requires POWER_AUTOMATE_FLOW_URL")
        return PowerAutomateTeamsPublisher(flow_url=flow_url)
    raise ValueError(f"Unknown TEAMS_PUBLISHER_MODE: {mode!r}")
