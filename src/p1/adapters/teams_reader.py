"""
Teams read adapter -- interface (CHN-03)

Narrow interface for everything downstream needs from Teams: channels,
members, messages (with delta/since support), thread replies and
permalinks. Agent logic depends ONLY on this interface -- no Graph SDK
type or response shape may leak past it. MockTeamsReader and
GraphTeamsReader are interchangeable behind it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class TeamsChannel(BaseModel):
    id: str
    display_name: str


class TeamsMember(BaseModel):
    id: str
    display_name: str


class TeamsMessage(BaseModel):
    id: str
    channel_id: str
    author_id: str | None = None
    thread_root_id: str | None = None  # None if this is the root message
    posted_at: str  # ISO 8601, original post time -- never overwritten on edit
    edited_at: str | None = None
    deleted_at: str | None = None
    is_deleted: bool = False
    is_bot: bool = False
    body: str = ""
    permalink: str | None = None


class MessagePage(BaseModel):
    """One page of a list_messages() call: the messages plus the token to
    pass back in for the next incremental sync."""

    messages: list[TeamsMessage]
    delta_token: str


class TeamsReader(ABC):
    """Read-only access to allowlisted Teams channels. A read credential
    behind this interface must never be able to post -- see the separate
    publish adapter (CHN-22) for the write path."""

    @abstractmethod
    def list_channels(self) -> list[TeamsChannel]: ...

    @abstractmethod
    def list_channel_members(self, channel_id: str) -> list[TeamsMember]: ...

    @abstractmethod
    def list_messages(
        self,
        channel_id: str,
        since: str | None = None,
        delta_token: str | None = None,
    ) -> MessagePage:
        """since: ISO timestamp for an initial sync. delta_token: an opaque
        token from a prior call, for an incremental sync. If both are
        given, delta_token takes priority."""

    @abstractmethod
    def list_replies(self, message_id: str) -> list[TeamsMessage]: ...

    @abstractmethod
    def get_permalink(self, message_id: str) -> str: ...
