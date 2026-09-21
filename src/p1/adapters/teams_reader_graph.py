"""
GraphTeamsReader (CHN-03/CHN-05): the real implementation behind the
identical TeamsReader interface, calling Microsoft Graph.

LIVE-VERIFIED as of 2026-09-19 -- CHN-01's tenant admin consent landed,
and this class has read and persisted a real message from a real Teams
channel (`p1-agent-test`) against the real DigitalT3 tenant (see
scripts/run_live_ingest_p1_agent_test.py and DECISION_LOG.md's
2026-09-19 entries). The scored path (harness, CI, demo) still never
depends on this class -- every golden case and unit test runs against
MockTeamsReader on purpose (Gate G0b's own rule), so this file being
live doesn't change what CI needs.
"""

from __future__ import annotations

import logging
import time

import httpx

from p1.adapters.teams_reader import (
    DeltaLinkRejectedError,
    DeltaTokenExpiredError,
    MessagePage,
    TeamsChannel,
    TeamsMember,
    TeamsMessage,
    TeamsReader,
)

logger = logging.getLogger("p1.adapters.teams_reader_graph")

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
MAX_THROTTLE_RETRIES = 5


class GraphThrottledError(Exception):
    """Raised when Graph keeps returning HTTP 429 after the retry budget
    is exhausted. A transport-level concern specific to calling a real
    API over HTTP -- not part of the TeamsReader interface contract."""


class GraphTeamsReader(TeamsReader):
    def __init__(self, access_token: str, team_id: str, timeout: float = 30.0):
        self._team_id = team_id
        self._client = httpx.Client(
            base_url=GRAPH_BASE_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=timeout,
        )
        # Graph's reply/permalink endpoints need channel_id, but this
        # interface's list_replies/get_permalink take only message_id --
        # resolved from messages already seen via list_messages.
        self._channel_id_by_message_id: dict[str, str] = {}

    def list_channels(self) -> list[TeamsChannel]:
        resp = self._get_with_retry(f"/teams/{self._team_id}/channels")
        resp.raise_for_status()
        return [
            TeamsChannel(id=item["id"], display_name=item["displayName"])
            for item in resp.json().get("value", [])
        ]

    def list_channel_members(self, channel_id: str) -> list[TeamsMember]:
        resp = self._get_with_retry(f"/teams/{self._team_id}/channels/{channel_id}/members")
        resp.raise_for_status()
        return [
            TeamsMember(id=item.get("userId", item.get("id")), display_name=item.get("displayName", ""))
            for item in resp.json().get("value", [])
        ]

    def list_messages(
        self,
        channel_id: str,
        since: str | None = None,
        delta_token: str | None = None,
    ) -> MessagePage:
        url = delta_token if delta_token else f"/teams/{self._team_id}/channels/{channel_id}/messages/delta"
        resp = self._get_with_retry(url)

        if resp.status_code == 410:
            raise DeltaTokenExpiredError(
                f"Delta token expired for channel_id={channel_id!r}; caller must resync from scratch."
            )
        if resp.status_code == 400 and delta_token:
            # Known Graph-side bug (see DeltaLinkRejectedError's own
            # docstring): a nextLink Graph just handed back can come
            # back rejected the moment it's followed, with this exact
            # error text -- reproducible on an empty/newly created
            # channel. Narrowly matched on the actual error text so an
            # unrelated 400 (a real client-side mistake) still surfaces
            # normally via raise_for_status() below.
            body_text = resp.text
            if "DeltaToken" in body_text and "not supported" in body_text:
                raise DeltaLinkRejectedError(
                    f"Graph rejected its own continuation link for channel_id={channel_id!r}: "
                    f"{body_text[:300]!r}"
                )
        resp.raise_for_status()
        data = resp.json()

        messages = [self._parse_message(item, channel_id) for item in data.get("value", [])]
        for m in messages:
            self._channel_id_by_message_id[m.id] = channel_id

        # nextLink means more pages exist right now -- keep paging in this
        # same sync. deltaLink means this is the final page -- persist it
        # and stop; it's the starting point for the *next* sync.
        next_link = data.get("@odata.nextLink")
        delta_link = data.get("@odata.deltaLink")
        has_more = next_link is not None
        next_token = next_link or delta_link or ""

        return MessagePage(messages=messages, delta_token=next_token, has_more=has_more)

    def list_replies(self, message_id: str) -> list[TeamsMessage]:
        channel_id = self._resolve_channel_id(message_id)
        resp = self._get_with_retry(f"/teams/{self._team_id}/channels/{channel_id}/messages/{message_id}/replies")
        resp.raise_for_status()
        replies = [self._parse_message(item, channel_id) for item in resp.json().get("value", [])]
        for r in replies:
            self._channel_id_by_message_id[r.id] = channel_id
        return replies

    def get_permalink(self, message_id: str) -> str:
        channel_id = self._resolve_channel_id(message_id)
        resp = self._get_with_retry(f"/teams/{self._team_id}/channels/{channel_id}/messages/{message_id}")
        resp.raise_for_status()
        return resp.json().get("webUrl", "")

    def note_known_message(self, message_id: str, channel_id: str) -> None:
        """Seeds this reader's own _channel_id_by_message_id cache
        directly, for a message this process already knows belongs to
        channel_id (e.g. a root message read back from the local
        `messages` table, ingested by a *different*, no-longer-alive
        instance of this class in an earlier process tick) without
        needing to call list_messages() again on this instance first.

        2026-09-21 live finding (see DECISION_LOG.md): ScopedTeamsReader
        gained a same-named method for its own, separate cache, but
        this reader's cache is independent -- forwarding a known
        message_id/channel_id pair to the gate alone left this class's
        own cache empty, so list_replies() on a message ingested by an
        earlier tick's now-discarded GraphTeamsReader still raised
        KeyError here even after the gate let the call through.
        ScopedTeamsReader.note_known_message() now forwards to this
        method (duck-typed) precisely to close that gap."""
        self._channel_id_by_message_id[message_id] = channel_id

    def _resolve_channel_id(self, message_id: str) -> str:
        channel_id = self._channel_id_by_message_id.get(message_id)
        if channel_id is None:
            raise KeyError(
                f"Unknown channel for message_id={message_id!r} -- list_messages() "
                "must be called for its channel before list_replies/get_permalink."
            )
        return channel_id

    def _get_with_retry(self, url: str) -> httpx.Response:
        """GET with Graph-specific throttling behaviour: honour HTTP 429
        and its Retry-After header, up to a bounded number of attempts.
        Any other status (including 410, handled by the caller) is
        returned as-is without retrying."""
        for attempt in range(1, MAX_THROTTLE_RETRIES + 1):
            resp = self._client.get(url)
            if resp.status_code != 429:
                return resp
            retry_after = float(resp.headers.get("Retry-After", "1"))
            logger.warning(
                "Graph throttled (429) on %s, waiting %.1fs (attempt %d/%d)",
                url, retry_after, attempt, MAX_THROTTLE_RETRIES,
            )
            time.sleep(retry_after)
        raise GraphThrottledError(f"Exceeded {MAX_THROTTLE_RETRIES} retries against {url} after repeated 429 throttling")

    @staticmethod
    def _parse_message(item: dict, channel_id: str) -> TeamsMessage:
        from_user = (item.get("from") or {}).get("user") or {}
        body = (item.get("body") or {}).get("content", "")
        return TeamsMessage(
            id=item["id"],
            channel_id=channel_id,
            author_id=from_user.get("id"),
            thread_root_id=item.get("replyToId"),
            posted_at=item.get("createdDateTime", ""),
            edited_at=item.get("lastEditedDateTime"),
            deleted_at=item.get("deletedDateTime"),
            is_deleted=item.get("deletedDateTime") is not None,
            is_bot=(item.get("from") or {}).get("application") is not None,
            is_system=item.get("messageType") == "systemEventMessage",
            body=body,
            permalink=item.get("webUrl"),
        )
