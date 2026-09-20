"""
Ingestion orchestrator (CHN-05): syncs one or all allowlisted channels
by draining pages from a TeamsReader (following has_more within a
single run), persisting the delta token via SyncStateStore, storing
messages via MessageStore, and recovering from an expired delta token
by clearing it and resyncing that channel from scratch.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from p1.adapters.teams_reader import DeltaLinkRejectedError, DeltaTokenExpiredError, TeamsReader
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore


class ChannelSyncResult(BaseModel):
    channel_id: str
    messages_ingested: int
    resynced: bool = False  # True if an expired delta token forced a full resync


def sync_channel(
    reader: TeamsReader,
    channel_id: str,
    sync_state: SyncStateStore,
    message_store: MessageStore,
) -> ChannelSyncResult:
    token = sync_state.get_delta_token(channel_id)
    try:
        count = _drain_pages(reader, channel_id, token, sync_state, message_store)
        return ChannelSyncResult(channel_id=channel_id, messages_ingested=count)
    except DeltaTokenExpiredError:
        sync_state.clear_delta_token(channel_id)
        count = _drain_pages(reader, channel_id, None, sync_state, message_store)
        return ChannelSyncResult(channel_id=channel_id, messages_ingested=count, resynced=True)


def sync_all_allowlisted_channels(
    reader: TeamsReader,
    channel_ids: Iterable[str],
    sync_state: SyncStateStore,
    message_store: MessageStore,
) -> list[ChannelSyncResult]:
    """channel_ids is the explicit allowlist to sync -- in production,
    ChannelConfigStore().list_allowlisted_channels() (config/channels/*.yaml),
    the same source ScopedTeamsReader itself builds its allowlist from.

    This used to discover channels by calling reader.list_channels()
    against Graph, which needs its own permission (Channel.ReadBasic.All)
    beyond ChannelMessage.Read.All -- see DECISION_LOG.md's CHN-01
    follow-up. Reading the allowlist from config instead means ingestion
    no longer needs that permission at all: config already knows which
    channels are in scope, so there's nothing left for Graph to tell us.

    reader is still expected to be scope-gated (CHN-04) as defense in
    depth: if channel_ids ever included something not actually on the
    allowlist, sync_channel() -> reader.list_messages() would still
    refuse it with ScopeViolationError rather than silently ingesting
    it -- this function's own channel_ids argument is not trusted to be
    the only thing standing between it and an out-of-scope read.
    """
    return [
        sync_channel(reader, channel_id, sync_state, message_store)
        for channel_id in channel_ids
    ]


def _drain_pages(
    reader: TeamsReader,
    channel_id: str,
    token: str | None,
    sync_state: SyncStateStore,
    message_store: MessageStore,
) -> int:
    count = 0
    last_good_token = token  # the most recent position we know Graph will actually accept
    while True:
        try:
            page = reader.list_messages(channel_id, delta_token=token)
        except DeltaLinkRejectedError:
            # See DeltaLinkRejectedError's own docstring (a known Graph
            # bug, first reproduced 2026-09-20 against a brand-new empty
            # channel): the continuation link we were just handed and
            # are now trying to follow is itself rejected. Retrying it,
            # or restarting this same sync from scratch, reproduces the
            # identical rejection -- so instead we stop paging here and
            # persist the last position that actually worked
            # (last_good_token, possibly None), not the rejected link.
            sync_state.save_delta_token(channel_id, last_good_token)
            return count
        message_store.upsert_messages(page.messages)
        count += len(page.messages)
        last_good_token = token
        token = page.delta_token
        if not page.has_more:
            break
    sync_state.save_delta_token(channel_id, token)
    return count
