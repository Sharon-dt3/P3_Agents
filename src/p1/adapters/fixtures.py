"""
Loads teams fixtures data for MockTeamsReader. CHN-06 populates the real 150-250 message seed here on Day 3; this module just
defines the format and loads whatever is present. Format, under seed/fixtures:
    channels.json: list of {id, display_name}
    members.json: {channel_id: [{id, display_name, email, tenant_status}]}
    members.json -- {channel_id: [{...TeamsMessage fields...}]} 
"""

from __future__ import annotations

import json
from pathlib import Path

from p1.adapters.teams_reader import TeamsChannel, TeamsMember, TeamsMessage

DEFAULT_FIXTURES_DIR = Path("seed/fixtures")

def load_teams_fixtures(
    fixtures_dir: str | Path = DEFAULT_FIXTURES_DIR,
) -> tuple[list[TeamsChannel], dict[str, list[TeamsMember]], dict[str, list[TeamsMessage]]]:
    fixtures_dir = Path(fixtures_dir)

    channels_raw = json.loads((fixtures_dir / "channels.json").read_text())
    members_raw = json.loads((fixtures_dir / "members.json").read_text())
    messages_raw = json.loads((fixtures_dir / "messages.json").read_text())

    channels = [TeamsChannel.model_validate(c) for c in channels_raw]
    members = {
        channel_id: [TeamsMember.model_validate(m) for m in members_list]
        for channel_id, members_list in members_raw.items()
    }
    messages = {
        channel_id: [TeamsMessage.model_validate(m) for m in messages_list]
        for channel_id, messages_list in messages_raw.items()
    }
    return channels, members, messages