"""
MockTeamsReader (CHN-03): serves fixture data over the identical
TeamsReader interface, with zero network egress.
"""

from __future__ import annotations

from pathlib import Path

from p1.adapters.fixtures import DEFAULT_FIXTURES_DIR, load_teams_fixtures
from p1.adapters.teams_reader import (
    MessagePage,
    TeamsChannel,
    TeamsMember,
    TeamsMessage,
    TeamsReader,
)


class MockTeamsReader(TeamsReader):
    def __init__(
        self,
        channels: list[TeamsChannel],
        members: dict[str, list[TeamsMember]],
        messages: dict[str, list[TeamsMessage]],
    ):
        self._channels = channels
        self._members = members
        self._messages = {
            channel_id: sorted(msgs, key=lambda m: m.posted_at)
            for channel_id, msgs in messages.items()
        }

    @classmethod
    def from_fixtures(cls, fixtures_dir: str | Path = DEFAULT_FIXTURES_DIR) -> MockTeamsReader:
        channels, members, messages = load_teams_fixtures(fixtures_dir)
        return cls(channels, members, messages)

    def list_channels(self) -> list[TeamsChannel]:
        return list(self._channels)

    def list_channel_members(self, channel_id: str) -> list[TeamsMember]:
        return list(self._members.get(channel_id, []))

    def list_messages(
        self,
        channel_id: str,
        since: str | None = None,
        delta_token: str | None = None,
    ) -> MessagePage:
        all_messages = self._messages.get(channel_id, [])

        if delta_token is not None:
            page = all_messages[int(delta_token):]
        elif since is not None:
            page = [m for m in all_messages if m.posted_at > since]
        else:
            page = list(all_messages)

        # The mock never paginates -- it always returns everything in one
        # page, so has_more is always False (there's nothing to keep
        # looping for within a single sync).
        return MessagePage(messages=page, delta_token=str(len(all_messages)), has_more=False)

    def list_replies(self, message_id: str) -> list[TeamsMessage]:
        replies = []
        for messages in self._messages.values():
            replies.extend(m for m in messages if m.thread_root_id == message_id)
        return replies

    def get_permalink(self, message_id: str) -> str:
        for messages in self._messages.values():
            for message in messages:
                if message.id == message_id:
                    return message.permalink or f"https://teams.microsoft.com/l/message/{message.channel_id}/{message_id}"
        raise KeyError(f"No message found with id={message_id!r}")
