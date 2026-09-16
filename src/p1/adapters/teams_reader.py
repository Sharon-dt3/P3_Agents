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


class DeltaTokenExpiredError(Exception):
    """Raised by a reader when a delta token it was given is no longer
    valid (e.g. Graph's HTTP 410 Gone). Part of the interface contract,
    not a Graph-only detail -- the caller's correct response is always
    the same regardless of which reader raised it: clear the persisted
    token for that channel and restart with a full sync (delta_token=None)."""


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
    is_system: bool = False
    body: str = ""
    permalink: str | None = None


class MessagePage(BaseModel):
    """One page of a list_messages() call: the messages, the token to pass
    back in next time, and whether more pages are available right now.

    has_more=True means there are more pages in THIS sync -- keep calling
    list_messages with the returned delta_token immediately. has_more=False
    means this is the final page -- persist the token and stop; it's for
    the *next* sync, not this one."""

    messages: list[TeamsMessage]
    delta_token: str
    has_more: bool = False


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
        given, delta_token takes priority. May raise DeltaTokenExpiredError
        if delta_token is no longer valid."""

    @abstractmethod
    def list_replies(self, message_id: str) -> list[TeamsMessage]: ...

    @abstractmethod
    def get_permalink(self, message_id: str) -> str: ...
