"""
GraphTeamsReader (CHN-03/CHN-05): the real implementation behind the
identical TeamsReader interface, calling Microsoft Graph.

NOT YET EXERCISED AGAINST A LIVE TENANT -- CHN-01's admin consent is
still outstanding (see DECISION_LOG.md). Written against the documented
Graph API shape so it's ready to wire in; the scored path (harness, CI,
demo) never depends on this class.
"""

from __future__ import annotations

import logging
import time

import httpx

from p1.adapters.teams_reader import (
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
