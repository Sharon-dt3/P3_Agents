import pytest

from p1.adapters.teams_reader import (
    DeltaTokenExpiredError,
    MessagePage,
    TeamsChannel,
    TeamsMessage,
)
from p1.adapters.teams_reader_mock import MockTeamsReader
from p1.ingestion.sync import sync_channel
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'Channel One', 1)")
    conn.execute("INSERT INTO members (id, display_name) VALUES ('u1', 'User One')")
    conn.commit()
    conn.close()
    return path


def _reader(messages):
    channels = [TeamsChannel(id="c1", display_name="Channel One")]
    return MockTeamsReader(channels, {"c1": []}, {"c1": messages})


def test_two_consecutive_syncs_produce_a_correct_incremental_set(db_path):
    sync_state = SyncStateStore(db_path)
    message_store = MessageStore(db_path)

    first_batch = [
        TeamsMessage(id="m1", channel_id="c1", author_id="u1", posted_at="2026-09-01T09:00:00Z", body="first"),
        TeamsMessage(id="m2", channel_id="c1", author_id="u1", posted_at="2026-09-01T09:05:00Z", body="second"),
    ]
    result1 = sync_channel(_reader(first_batch), "c1", sync_state, message_store)
    assert result1.messages_ingested == 2

    second_batch = first_batch + [
        TeamsMessage(id="m3", channel_id="c1", author_id="u1", posted_at="2026-09-01T09:10:00Z", body="third"),
    ]
    result2 = sync_channel(_reader(second_batch), "c1", sync_state, message_store)
    # Only the new message should be ingested this run -- the persisted
    # delta token from run 1 skips m1 and m2.
    assert result2.messages_ingested == 1

    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"]
    finally:
        conn.close()
    assert count == 3


def test_edited_message_keeps_its_original_post_time(db_path):
    message_store = MessageStore(db_path)

    original = TeamsMessage(
        id="m1", channel_id="c1", author_id="u1",
        posted_at="2026-09-01T09:00:00Z", body="original text",
    )
    message_store.upsert_messages([original])

    # Deliberately pass a different posted_at on the "edit" to prove the
    # store itself refuses to let it through -- not just that our own
    # readers happen to always send the same value back.
    edited = TeamsMessage(
        id="m1", channel_id="c1", author_id="u1",
        posted_at="2026-09-01T23:59:59Z",
        edited_at="2026-09-01T10:00:00Z",
        body="edited text",
    )
    message_store.upsert_messages([edited])

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT posted_at, edited_at, body_raw FROM messages WHERE id = 'm1'").fetchone()
    finally:
        conn.close()

    assert row["posted_at"] == "2026-09-01T09:00:00Z"
    assert row["edited_at"] == "2026-09-01T10:00:00Z"
    assert row["body_raw"] == "edited text"


def test_bot_and_system_flags_are_stored_correctly(db_path):
    message_store = MessageStore(db_path)

    bot_message = TeamsMessage(
        id="m1", channel_id="c1", posted_at="2026-09-01T09:00:00Z",
        body="Build #452 succeeded", is_bot=True,
    )
    system_message = TeamsMessage(
        id="m2", channel_id="c1", posted_at="2026-09-01T09:05:00Z",
        body="added Priya to the channel", is_system=True,
    )
    message_store.upsert_messages([bot_message, system_message])

    conn = get_connection(db_path)
    try:
        rows = {
            row["id"]: (row["is_bot"], row["is_system"])
            for row in conn.execute("SELECT id, is_bot, is_system FROM messages")
        }
    finally:
        conn.close()

    assert rows["m1"] == (1, 0)
    assert rows["m2"] == (0, 1)


def test_expired_delta_token_triggers_a_clean_resync(db_path):
    sync_state = SyncStateStore(db_path)
    sync_state.save_delta_token("c1", "stale-token")
    message_store = MessageStore(db_path)

    class ExpiringThenFreshReader:
        def __init__(self, messages):
            self._messages = messages

        def list_channels(self):
            return [TeamsChannel(id="c1", display_name="Channel One")]

        def list_channel_members(self, channel_id):
            return []

        def list_messages(self, channel_id, since=None, delta_token=None):
            if delta_token == "stale-token":
                raise DeltaTokenExpiredError("token expired")
            return MessagePage(messages=self._messages, delta_token="fresh-token", has_more=False)

        def list_replies(self, message_id):
            return []

        def get_permalink(self, message_id):
            return ""

    messages = [TeamsMessage(id="m1", channel_id="c1", posted_at="2026-09-01T09:00:00Z", body="hi")]
    reader = ExpiringThenFreshReader(messages)

    result = sync_channel(reader, "c1", sync_state, message_store)
    assert result.resynced is True
    assert result.messages_ingested == 1
    assert sync_state.get_delta_token("c1") == "fresh-token"
