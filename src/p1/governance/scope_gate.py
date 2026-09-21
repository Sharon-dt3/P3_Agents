"""
Scope gate (CHN-04): the structural boundary that makes it impossible to
read a non-allowlisted channel or any chat, rather than merely unlikely.

Wraps a TeamsReader and refuses list_messages()/list_channel_members()
for any channel_id that is not on the explicit allowlist, persisting a
refusal record to the audit table before raising. list_channels() is
filtered down to allowlisted channels only, since it is enumeration, not
a denied request.

list_replies()/get_permalink() take only a message_id, not a channel_id
-- this gate resolves which channel that message_id belongs to from its
OWN record of every message_id a gated list_messages()/list_replies()
call has actually returned (_channel_id_by_message_id, populated here,
not borrowed from whatever the wrapped reader happens to track
internally), and enforces the allowlist against that. A message_id this
gate has never itself seen is refused outright.

2026-09-20 finding: an earlier version of this class delegated these two
calls straight to the wrapped reader with no check at all here, relying
entirely on GraphTeamsReader's own internal message_id->channel_id cache
to make an out-of-scope call impossible in practice -- true only as long
as every TeamsReader implementation happens to enforce that invariant
itself, which is exactly the kind of "merely unlikely, not structurally
impossible" gap this module's own docstring says is not good enough. See
DECISION_LOG.md.
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
        # This gate's own record of which channel a message_id belongs
        # to, populated only from messages THIS gate has already let
        # through -- never trusted from the wrapped reader's own
        # bookkeeping. See this module's docstring for why.
        self._channel_id_by_message_id: dict[str, str] = {}

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
        page = self._reader.list_messages(channel_id, since=since, delta_token=delta_token)
        for message in page.messages:
            self._channel_id_by_message_id[message.id] = channel_id
        return page

    def list_replies(self, message_id: str) -> list[TeamsMessage]:
        channel_id = self._resolve_channel_id(message_id, "list_replies")
        replies = self._reader.list_replies(message_id)
        for reply in replies:
            self._channel_id_by_message_id[reply.id] = channel_id
        return replies

    def get_permalink(self, message_id: str) -> str:
        self._resolve_channel_id(message_id, "get_permalink")
        return self._reader.get_permalink(message_id)

    def note_known_message(self, message_id: str, channel_id: str) -> None:
        """Lets a caller re-establish a message_id this gate already
        legitimately saw in an earlier process tick as known, without
        re-fetching it through list_messages()/list_replies() again.

        _channel_id_by_message_id lives only in memory (see this
        module's own docstring), so a fresh ScopedTeamsReader instance
        -- built new every ingestion poll, e.g. by
        scripts/live_runner_*.py's own _poll_ingest() -- starts each
        tick with no memory of messages a *previous* tick's gate
        instance already saw and persisted to `messages`. Without this,
        list_replies() on a root message ingested in an earlier tick
        would raise ScopeViolationError forever, even though that root
        message is already known-good, on-allowlist, committed data --
        not a bypass of the gate, just a way to hand it back its own
        prior, already-legitimate finding.

        Still runs through _enforce() first: a caller cannot use this to
        smuggle an out-of-scope channel_id past the allowlist -- it can
        only ever re-assert something for a channel already in scope.

        2026-09-21 live finding (see DECISION_LOG.md): seeding only
        THIS gate's own cache was not enough on its own -- GraphTeamsReader
        keeps its own, entirely separate _channel_id_by_message_id cache
        (see teams_reader_graph.py's own docstring), and list_replies()
        below delegates to self._reader.list_replies(), which resolves
        channel_id from *that* cache, not this one. Without also seeding
        the wrapped reader, a message this gate now considers known
        still made self._reader.list_replies() raise KeyError. Forwarded
        here via duck-typing (getattr/callable), not an isinstance check
        against GraphTeamsReader specifically, so this keeps working for
        any TeamsReader implementation that needs the same seeding, and
        does nothing extra for one that doesn't (MockTeamsReader has no
        such method and needs none -- its own list_replies() scans every
        channel's messages directly, with no cache to seed)."""
        self._enforce(channel_id, "note_known_message")
        self._channel_id_by_message_id[message_id] = channel_id
        note_on_wrapped = getattr(self._reader, "note_known_message", None)
        if callable(note_on_wrapped):
            note_on_wrapped(message_id, channel_id)

    def _resolve_channel_id(self, message_id: str, operation: str) -> str:
        """The independent check list_replies()/get_permalink() were
        previously missing -- see this module's own docstring. A
        message_id this gate has never itself returned from a gated
        list_messages()/list_replies() call is refused outright, exactly
        like an out-of-scope channel_id; a known message_id is then
        re-checked against the current allowlist the same way, so a
        channel removed from the allowlist after its messages were seen
        is refused here too, not just for future list_messages() calls."""
        channel_id = self._channel_id_by_message_id.get(message_id)
        if channel_id is None:
            reason = "message_id was never returned by a prior gated call on this reader"
            self._record_refusal(message_id, operation, reason, entity_type="message")
            raise ScopeViolationError(f"Refused {operation} for message_id={message_id!r}: {reason}")
        self._enforce(channel_id, operation)
        return channel_id

    def _enforce(self, channel_id: str, operation: str) -> None:
        if channel_id in self._allowlist:
            return
        reason = "channel_id is not on the explicit allowlist"
        self._record_refusal(channel_id, operation, reason, entity_type="channel")
        raise ScopeViolationError(f"Refused {operation} for channel_id={channel_id!r}: {reason}")

    def _record_refusal(self, entity_id: str, operation: str, reason: str, *, entity_type: str) -> None:
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
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "details": json.dumps({"operation": operation, "reason": reason}),
                },
            )
            conn.commit()
        finally:
            conn.close()
