"""
Ingestion orchestrator (CHN-05): syncs one or all allowlisted channels
by draining pages from a TeamsReader (following has_more within a
single run), persisting the delta token via SyncStateStore, storing
messages via MessageStore, and recovering from an expired delta token
by clearing it and resyncing that channel from scratch.
"""

from __future__ import annotations

from pydantic import BaseModel

from p1.adapters.teams_reader import DeltaTokenExpiredError, TeamsReader
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
    sync_state: SyncStateStore,
    message_store: MessageStore,
) -> list[ChannelSyncResult]:
    """reader is expected to already be scope-gated (CHN-04) -- list_channels()
    only ever returns allowlisted channels, so this never has to re-check
    scope itself."""
    return [
        sync_channel(reader, channel.id, sync_state, message_store)
        for channel in reader.list_channels()
    ]


def _drain_pages(
    reader: TeamsReader,
    channel_id: str,
    token: str | None,
    sync_state: SyncStateStore,
    message_store: MessageStore,
) -> int:
    count = 0
    while True:
        page = reader.list_messages(channel_id, delta_token=token)
        message_store.upsert_messages(page.messages)
        count += len(page.messages)
        token = page.delta_token
        if not page.has_more:
            break
    sync_state.save_delta_token(channel_id, token)
    return count
