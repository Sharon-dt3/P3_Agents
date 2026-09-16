"""
GraphTeamsReader (CHN-03): the real implementation behind the identical
TeamsReader interface, calling Microsoft Graph.

NOT YET EXERCISED AGAINST A LIVE TENANT -- CHN-01's admin consent is
still outstanding (see DECISION_LOG.md). Written against the documented
Graph API shape so it's ready to wire in; the scored path (harness, CI,
demo) never depends on this class.
"""

from __future__ import annotations

import httpx

from p1.adapters.teams_reader import (
    MessagePage,
    TeamsChannel,
    TeamsMember,
    TeamsMessage,
    TeamsReader,
)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


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
        resp = self._client.get(f"/teams/{self._team_id}/channels")
        resp.raise_for_status()
        return [
            TeamsChannel(id=item["id"], display_name=item["displayName"])
            for item in resp.json().get("value", [])
        ]

    def list_channel_members(self, channel_id: str) -> list[TeamsMember]:
        resp = self._client.get(f"/teams/{self._team_id}/channels/{channel_id}/members")
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
        resp = self._client.get(url)
        resp.raise_for_status()
        data = resp.json()

        messages = [self._parse_message(item, channel_id) for item in data.get("value", [])]
        for m in messages:
            self._channel_id_by_message_id[m.id] = channel_id

        next_token = data.get("@odata.deltaLink") or data.get("@odata.nextLink") or ""
        return MessagePage(messages=messages, delta_token=next_token)

    def list_replies(self, message_id: str) -> list[TeamsMessage]:
        channel_id = self._resolve_channel_id(message_id)
        resp = self._client.get(f"/teams/{self._team_id}/channels/{channel_id}/messages/{message_id}/replies")
        resp.raise_for_status()
        replies = [self._parse_message(item, channel_id) for item in resp.json().get("value", [])]
        for r in replies:
            self._channel_id_by_message_id[r.id] = channel_id
        return replies

    def get_permalink(self, message_id: str) -> str:
        channel_id = self._resolve_channel_id(message_id)
        resp = self._client.get(f"/teams/{self._team_id}/channels/{channel_id}/messages/{message_id}")
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
            body=body,
            permalink=item.get("webUrl"),
        )
