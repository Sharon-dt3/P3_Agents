"""
Regression guard for a real, previously-open gap (see DECISION_LOG.md
and README.md's CHN-31 entry): ingesting a message from an author never
seen before used to crash outright with a foreign key violation
(messages.author_id references members(id), and PRAGMA foreign_keys is
ON -- see p1.storage.db) unless some caller had separately pre-inserted
that author into `members` from its own fixture data first. Only
scripts/run_daily.py, scripts/run_walkthrough.py and
p1.eval.chn12_cases did that, and only for their own committed fixture
authors -- nothing did it for a real, live Graph sync, where the
authors are not known ahead of time.

These tests exercise MessageStore.upsert_messages() directly, with NO
pre-seeded members row and NO fixture data involved at all, to prove
the fix lives in the one place every reader's messages actually pass
through, not in any particular caller.
"""

from __future__ import annotations

from p1.adapters.teams_reader import TeamsMessage
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore


def _bare_db(tmp_path):
    """A channel row only -- deliberately NO members row pre-inserted,
    unlike every other test in this suite's own db_path fixture. This
    is the exact condition (a never-before-seen author) that used to
    crash."""
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'Channel One', 1)")
    conn.commit()
    conn.close()
    return path


def test_ingesting_a_never_before_seen_author_no_longer_crashes(tmp_path):
    db_path = _bare_db(tmp_path)
    message_store = MessageStore(db_path)

    message = TeamsMessage(
        id="m1", channel_id="c1", author_id="brand-new-author",
        posted_at="2026-09-18T09:00:00Z", body="hello",
    )

    # This is the actual regression: previously raised
    # sqlite3.IntegrityError: FOREIGN KEY constraint failed.
    message_store.upsert_messages([message])

    conn = get_connection(db_path)
    try:
        member_row = conn.execute(
            "SELECT id, display_name FROM members WHERE id = 'brand-new-author'"
        ).fetchone()
        message_row = conn.execute("SELECT author_id FROM messages WHERE id = 'm1'").fetchone()
    finally:
        conn.close()

    assert member_row is not None, "author was never auto-registered into members"
    assert member_row["display_name"] == "brand-new-author"
    assert message_row["author_id"] == "brand-new-author"


def test_a_message_with_no_author_never_touches_members_at_all(tmp_path):
    """A system/bot message can legitimately have author_id=None (see
    test_bot_and_system_flags_are_stored_correctly in
    test_ingestion_sync.py) -- must never attempt an INSERT with a NULL
    id, which would itself be a bug, not a feature."""
    db_path = _bare_db(tmp_path)
    message_store = MessageStore(db_path)

    message = TeamsMessage(
        id="m1", channel_id="c1", posted_at="2026-09-18T09:00:00Z",
        body="added Priya to the channel", is_system=True,
    )
    message_store.upsert_messages([message])

    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) AS n FROM members").fetchone()["n"]
    finally:
        conn.close()
    assert count == 0


def test_an_already_known_member_is_never_overwritten(tmp_path):
    """INSERT OR IGNORE must mean exactly that -- a richer display name
    a future, real member-sync populates (see this module's own
    _ensure_member_exists docstring) must never be clobbered back to
    the plain author_id placeholder by a later message from that same
    author."""
    db_path = _bare_db(tmp_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO members (id, display_name) VALUES ('u1', 'Sharon Silva')")
    conn.commit()
    conn.close()

    message_store = MessageStore(db_path)
    message_store.upsert_messages([
        TeamsMessage(id="m1", channel_id="c1", author_id="u1", posted_at="2026-09-18T09:00:00Z", body="hi"),
    ])

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT display_name FROM members WHERE id = 'u1'").fetchone()
    finally:
        conn.close()
    assert row["display_name"] == "Sharon Silva"


def test_list_root_message_ids_returns_only_non_reply_non_deleted_messages(tmp_path):
    # The exact set MessageStore.list_root_message_ids() exists to
    # produce: a caller (live_runner_*.py's _poll_ingest(), via
    # ingestion.sync.sync_channel_replies()) needs every root this
    # channel has -- a reply itself is never a valid root to fetch
    # replies-of, and a deleted root's thread is no longer worth
    # re-polling every tick. See DECISION_LOG.md's
    # thread-replies-ingestion entry.
    db_path = _bare_db(tmp_path)
    message_store = MessageStore(db_path)

    root_message = TeamsMessage(
        id="m1", channel_id="c1", author_id="u1",
        posted_at="2026-09-18T09:00:00Z", body="root",
    )
    reply_message = TeamsMessage(
        id="m1-r1", channel_id="c1", author_id="u2",
        posted_at="2026-09-18T09:05:00Z", body="a reply", thread_root_id="m1",
    )
    deleted_root = TeamsMessage(
        id="m2", channel_id="c1", author_id="u1",
        posted_at="2026-09-18T09:10:00Z", body="deleted root", is_deleted=True,
    )
    message_store.upsert_messages([root_message, reply_message, deleted_root])

    root_ids = message_store.list_root_message_ids("c1")

    assert root_ids == ["m1"]


def test_list_root_message_ids_is_scoped_to_its_own_channel(tmp_path):
    db_path = _bare_db(tmp_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c2', 'Channel Two', 1)")
    conn.commit()
    conn.close()

    message_store = MessageStore(db_path)
    message_store.upsert_messages([
        TeamsMessage(id="m1", channel_id="c1", author_id="u1", posted_at="2026-09-18T09:00:00Z", body="c1 root"),
        TeamsMessage(id="m2", channel_id="c2", author_id="u1", posted_at="2026-09-18T09:00:00Z", body="c2 root"),
    ])

    assert message_store.list_root_message_ids("c1") == ["m1"]
    assert message_store.list_root_message_ids("c2") == ["m2"]


def test_list_root_message_ids_honours_the_since_lower_bound(tmp_path):
    db_path = _bare_db(tmp_path)
    message_store = MessageStore(db_path)
    message_store.upsert_messages([
        TeamsMessage(id="early", channel_id="c1", author_id="u1", posted_at="2026-09-01T00:00:00Z", body="old"),
        TeamsMessage(id="late", channel_id="c1", author_id="u1", posted_at="2026-09-18T00:00:00Z", body="new"),
    ])

    assert message_store.list_root_message_ids("c1", since="2026-09-10T00:00:00Z") == ["late"]
