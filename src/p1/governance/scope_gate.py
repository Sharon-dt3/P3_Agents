"""
Scope gate (CHN-04): the structural boundary that makes it impossible to
read a non-allowlisted channel or any chat, rather than merely unlikely.

Wraps a TeamsReader and refuses list_messages()/list_channel_members()
for any channel_id that is not on the explicit allowlist, persisting a
refusal record to the audit table before raising. list_replies() and
get_permalink() take only a message_id -- by construction that
message_id can only ever have come from a prior, already-gated
list_messages() call, so there is no separate channel to check there.
list_channels() is filtered down to allowlisted channels only, since it
is enumeration, not a denied request.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

from p1.adapters.teams_reader import (
    MessagePage,
    TeamsChannel,
    TeamsMember,
    TeamsMessage,
    TeamsReader,
)
from p1.storage.db import DEFAULT_DB_PATH, get_connection


class ScopeViolationError(Exception):
    """Raised when a read is attempted against a channel_id that is not
    on the explicit allowlist. Never caught and silently swallowed --
    a caller must handle it deliberately."""


class ScopedTeamsReader(TeamsReader):
    """Wraps any TeamsReader and enforces the channel allowlist at the
    adapter boundary. Drop-in replacement for the reader it wraps --
    identical interface (Liskov substitution)."""

    def __init__(
        self,
        reader: TeamsReader,
        allowlisted_channel_ids: Iterable[str],
        db_path: str = DEFAULT_DB_PATH,
    ):
        self._reader = reader
        self._allowlist = set(allowlisted_channel_ids)
        self._db_path = db_path

    @property
    def wrapped_reader(self) -> TeamsReader:
        """The concrete reader this gate wraps -- exposed for tests and
        introspection only. Application code should depend on the
        TeamsReader interface and never reach through this to bypass
        the gate."""
        return self._reader

    def list_channels(self) -> list[TeamsChannel]:
        return [c for c in self._reader.list_channels() if c.id in self._allowlist]

    def list_channel_members(self, channel_id: str) -> list[TeamsMember]:
        self._enforce(channel_id, "list_channel_members")
        return self._reader.list_channel_members(channel_id)

    def list_messages(
        self,
        channel_id: str,
        since: str | None = None,
        delta_token: str | None = None,
    ) -> MessagePage:
        self._enforce(channel_id, "list_messages")
        return self._reader.list_messages(channel_id, since=since, delta_token=delta_token)

    def list_replies(self, message_id: str) -> list[TeamsMessage]:
        return self._reader.list_replies(message_id)

    def get_permalink(self, message_id: str) -> str:
        return self._reader.get_permalink(message_id)

    def _enforce(self, channel_id: str, operation: str) -> None:
        if channel_id in self._allowlist:
            return
        reason = "channel_id is not on the explicit allowlist"
        self._record_refusal(channel_id, operation, reason)
        raise ScopeViolationError(f"Refused {operation} for channel_id={channel_id!r}: {reason}")

    def _record_refusal(self, channel_id: str, operation: str, reason: str) -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO audit (actor, action, entity_type, entity_id, details)
                VALUES (:actor, :action, :entity_type, :entity_id, :details)
                """,
                {
                    "actor": "scope_gate",
                    "action": "refuse_read",
                    "entity_type": "channel",
                    "entity_id": channel_id,
                    "details": json.dumps({"operation": operation, "reason": reason}),
                },
            )
            conn.commit()
        finally:
            conn.close()
