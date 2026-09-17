import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.grounding.message_lookup import sqlite_message_lookup
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'Channel One', 1)")
    conn.execute("INSERT INTO members (id, display_name) VALUES ('alice', 'Alice')")
    conn.commit()
    conn.close()
    return path


def test_resolves_a_real_messages_raw_body(db_path):
    message = TeamsMessage(
        id="m1", channel_id="c1", author_id="alice",
        posted_at="2025-06-02T09:30:00+05:30", body="Finished the auth flow, running the tests now.",
    )
    MessageStore(db_path).upsert_messages([message])

    lookup = sqlite_message_lookup(db_path)
    assert lookup("m1") == "Finished the auth flow, running the tests now."


def test_unknown_message_id_resolves_to_none(db_path):
    lookup = sqlite_message_lookup(db_path)
    assert lookup("does-not-exist") is None
