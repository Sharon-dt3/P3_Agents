"""
CHN-12 golden cases: GC5 (scope-gate hard zero) and GC10 (ingest
correctness across two delta runs) -- both "hard-zero assertions rather
than proportions" per this task's own acceptance test, unlike GC1's
gated proportion.

GC5 -- runs the real production wiring (p1.adapters.factory.
get_teams_reader(), which is what CHN-04's scope gate and CHN-03's
ingestion actually use in production) against the real committed
fixtures, via p1.ingestion.sync.sync_all_allowlisted_channels(). That
function only ever iterates the explicit channel_ids this case passes
in from ChannelConfigStore().list_allowlisted_channels() -- the same
config-driven allowlist ScopedTeamsReader itself is built from -- so
proj-gamma (config/channels/proj-gamma.yaml, allowlisted: false) is
never even named, let alone attempted, and the store should end up
with zero of its messages. (Before CHN-01's follow-up, this same
invariant held via reader.list_channels() instead, which Graph itself
filtered to the allowlist; sync_all_allowlisted_channels() no longer
calls that method at all -- see DECISION_LOG.md -- but the scope gate
still refuses any out-of-scope id at the reader boundary regardless of
where the caller's channel_id list came from, which is what the
direct-proof half below exercises.) That architectural invariant is
asserted directly (a hard-zero count), plus three direct proofs that
ScopeViolationError is actually raised for every kind of out-of-scope
id a caller might try: the non-allowlisted channel itself, and two
synthetic Teams chat ids (one 1:1-style, one group-style, both using
the "19:...@unq.gbl.spaces" id shape test_scope_gate.py already uses)
-- chats were never on the channel allowlist in the first place, so
the same channel_id check refuses them with no separate "is this a
chat" logic, exactly as test_list_messages_on_a_chat_id_raises_the_same_way
already proves for one id.

Note on the direct-proof half: p1.adapters.factory.get_teams_reader()
constructs its ScopedTeamsReader without ever passing a db_path, so the
reader it returns always records refusals against the module-level
default (data/p1.db, relative to the caller's cwd) regardless of which
db the caller is actually using elsewhere -- fine for the one-real-db
production process this was written for, but it means calling that
exact object's list_messages() on a refused id in an isolated test would
try to INSERT into an audit table in a database this golden case never
initialised (or, worse, quietly write a stray audit row into whatever
real data/p1.db happens to sit in the repo root). Flagged in
DECISION_LOG.md as an optional fix (passing db_path through
get_teams_reader() -> ScopedTeamsReader); not changed here, since it's
pre-existing factory.py code outside this WBS row's own scope -- the
same posture CHN-11 took with the ScriptedGateway substring bug. This
golden case works around it instead: the direct-proof half builds its
own ScopedTeamsReader from the same real ingredients get_teams_reader()
would use (MockTeamsReader.from_fixtures(), ChannelConfigStore()'s real
allowlist) but pointed at this case's own temp db, so the real scope-gate
logic and the real channel config are still exactly what's exercised.

GC10 -- a synthetic two-delta-run scenario (the real fixtures have no
distinct before/after snapshots to exercise an edit or a delete against)
built the same way test_ingestion_sync.py's own tests already do: a
second MockTeamsReader constructed from "run 1's messages plus some more
appended at the end", sharing one SyncStateStore/MessageStore/persisted
delta token across both sync_channel() calls. Run 2 appends four
messages: gc10-edit-1 and gc10-del-1 resent under their original ids
with new content -- and a deliberately different posted_at, to prove
the store's own upsert ignores whatever posted_at a delta redelivery
carries (messages_repo.py's ON CONFLICT clause never touches posted_at),
not merely that this test's own readers happen to resend the same value
-- plus two brand-new ids, gc10-bot-2 and gc10-sys-2, proving bot/system
flags are stored correctly for messages introduced by a later delta
page too, not just a channel's first sync. Every assertion here is a
hard pass/fail (an exact row count, an exact flag map via equals()), per
the acceptance test's own framing.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from p1.adapters.factory import get_teams_reader
from p1.adapters.fixtures import load_teams_fixtures
from p1.adapters.teams_reader import TeamsChannel, TeamsMessage
from p1.adapters.teams_reader_mock import MockTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.eval.cases import GoldenCase, GoldenCaseRegistry, MetricResult, at_most, equals
from p1.governance.scope_gate import ScopedTeamsReader, ScopeViolationError
from p1.ingestion.sync import sync_all_allowlisted_channels, sync_channel
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

GAMMA = "19:proj-gamma@thread.tacv2"

# Synthetic chat ids -- never configured channels at all, so they were
# never on the allowlist in the first place. Same id shape
# test_scope_gate.py already uses for its own chat-id check.
CHAT_ONE_TO_ONE = "19:one-to-one-chat@unq.gbl.spaces"
CHAT_GROUP = "19:another-group-chat@unq.gbl.spaces"

# --- GC5: scope gate hard zero ---------------------------------------------


@contextmanager
def _seeded_db_gc5():
    tmp_dir = tempfile.mkdtemp(prefix="chn12_gc5_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        ChannelConfigStore().sync_to_db(db_path)

        allowlisted = set(ChannelConfigStore().list_allowlisted_channels())
        _, _, messages_by_channel = load_teams_fixtures()
        in_scope_messages = [
            m for channel_id, msgs in messages_by_channel.items() if channel_id in allowlisted for m in msgs
        ]

        conn = get_connection(db_path)
        try:
            for author_id in sorted({m.author_id for m in in_scope_messages if m.author_id}):
                conn.execute(
                    "INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)",
                    (author_id, author_id),
                )
            conn.commit()
        finally:
            conn.close()

        yield db_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _measure_gc5() -> list[MetricResult]:
    with _seeded_db_gc5() as db_path:
        allowlisted = ChannelConfigStore().list_allowlisted_channels()
        sync_state = SyncStateStore(db_path)
        message_store = MessageStore(db_path)

        # The real production factory: MockTeamsReader wrapped in
        # ScopedTeamsReader, with the allowlist coming from the real
        # config/channels/*.yaml files -- exactly what CHN-03's
        # ingestion runs against in production.
        reader = get_teams_reader()
        sync_all_allowlisted_channels(reader, allowlisted, sync_state, message_store)

        placeholders = ", ".join("?" for _ in allowlisted)
        conn = get_connection(db_path)
        try:
            out_of_scope_count = conn.execute(
                f"SELECT COUNT(*) AS n FROM messages WHERE channel_id NOT IN ({placeholders})",
                allowlisted,
            ).fetchone()["n"]
        finally:
            conn.close()

        results = [
            MetricResult(
                metric_id="GC5-out-of-scope-message-count",
                name="out-of-scope messages in the store after a full ingest",
                measured=out_of_scope_count,
                target=0,
                comparator_name="at_most",
                passed=at_most(out_of_scope_count, 0),
                detail=f"{len(allowlisted)} allowlisted channel(s); proj-gamma's messages never attempted",
            )
        ]

        # Direct proofs, via a ScopedTeamsReader built from the same
        # real ingredients get_teams_reader() uses (see this module's
        # docstring for why this doesn't call get_teams_reader() itself
        # for this half).
        direct_reader = ScopedTeamsReader(MockTeamsReader.from_fixtures(), allowlisted, db_path=db_path)
        for label, target_id in (
            ("gamma-channel", GAMMA),
            ("one-to-one-chat", CHAT_ONE_TO_ONE),
            ("group-chat", CHAT_GROUP),
        ):
            refused = False
            try:
                direct_reader.list_messages(target_id)
            except ScopeViolationError:
                refused = True
            results.append(
                MetricResult(
                    metric_id=f"GC5-{label}-refused",
                    name=f"direct list_messages on the {label.replace('-', ' ')} is refused",
                    measured=refused,
                    target=True,
                    comparator_name="equals",
                    passed=equals(refused, True),
                    detail=f"channel_id={target_id!r}",
                )
            )
    return results


# --- GC10: ingest correctness across two delta runs -------------------------

GC10_CHANNEL_ID = "gc10-channel"

# The ids expected to carry is_bot / is_system after both delta runs --
# one of each planted in run 1, one of each planted fresh in run 2, to
# prove a later delta page gets the flags right too, not just a
# channel's first sync.
_GC10_BOT_IDS = frozenset({"gc10-bot-1", "gc10-bot-2"})
_GC10_SYSTEM_IDS = frozenset({"gc10-sys-1", "gc10-sys-2"})


def _gc10_message(
    message_id: str,
    *,
    posted_at: str,
    author_id: str | None = None,
    edited_at: str | None = None,
    deleted_at: str | None = None,
    is_deleted: bool = False,
    is_bot: bool = False,
    is_system: bool = False,
    body: str = "",
) -> TeamsMessage:
    return TeamsMessage(
        id=message_id,
        channel_id=GC10_CHANNEL_ID,
        author_id=author_id,
        posted_at=posted_at,
        edited_at=edited_at,
        deleted_at=deleted_at,
        is_deleted=is_deleted,
        is_bot=is_bot,
        is_system=is_system,
        body=body,
    )


def _gc10_reader(messages: list[TeamsMessage]) -> MockTeamsReader:
    channels = [TeamsChannel(id=GC10_CHANNEL_ID, display_name="GC10 Channel")]
    return MockTeamsReader(channels, {GC10_CHANNEL_ID: []}, {GC10_CHANNEL_ID: messages})


@contextmanager
def _seeded_db_gc10():
    tmp_dir = tempfile.mkdtemp(prefix="chn12_gc10_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)",
                (GC10_CHANNEL_ID, "GC10 Channel"),
            )
            for member_id in ("user.one", "user.two"):
                conn.execute(
                    "INSERT INTO members (id, display_name) VALUES (?, ?)",
                    (member_id, member_id),
                )
            conn.commit()
        finally:
            conn.close()
        yield db_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _measure_gc10() -> list[MetricResult]:
    with _seeded_db_gc10() as db_path:
        sync_state = SyncStateStore(db_path)
        message_store = MessageStore(db_path)

        run1_messages = [
            _gc10_message("gc10-m1", author_id="user.one", posted_at="2026-09-01T09:00:00Z", body="Deployed the export job."),
            _gc10_message("gc10-bot-1", posted_at="2026-09-01T09:01:00Z", is_bot=True, body="Build #100 succeeded"),
            _gc10_message("gc10-sys-1", posted_at="2026-09-01T09:02:00Z", is_system=True, body="added user.two to the channel"),
            _gc10_message("gc10-edit-1", author_id="user.one", posted_at="2026-09-01T09:03:00Z", body="Initial draft of the notes."),
            _gc10_message("gc10-del-1", author_id="user.two", posted_at="2026-09-01T09:04:00Z", body="Will delete this by mistake."),
        ]
        result1 = sync_channel(_gc10_reader(run1_messages), GC10_CHANNEL_ID, sync_state, message_store)

        run2_messages = run1_messages + [
            # Resent under gc10-edit-1's original id with new content and
            # a deliberately different posted_at than run 1's -- proves
            # the store itself refuses to let a delta redelivery move
            # posted_at, not just that this test's own reader happens to
            # always resend the same value (see test_ingestion_sync.py's
            # test_edited_message_keeps_its_original_post_time, which
            # makes the same point against MessageStore directly).
            _gc10_message(
                "gc10-edit-1",
                author_id="user.one",
                posted_at="2026-09-02T10:00:00Z",
                edited_at="2026-09-02T10:05:00Z",
                body="Finished the notes after all.",
            ),
            _gc10_message(
                "gc10-del-1",
                author_id="user.two",
                posted_at="2026-09-02T10:01:00Z",
                deleted_at="2026-09-02T10:06:00Z",
                is_deleted=True,
                body="Will delete this by mistake.",
            ),
            _gc10_message("gc10-bot-2", posted_at="2026-09-02T10:02:00Z", is_bot=True, body="Build #101 succeeded"),
            _gc10_message("gc10-sys-2", posted_at="2026-09-02T10:03:00Z", is_system=True, body="removed user.two from the channel"),
        ]
        result2 = sync_channel(_gc10_reader(run2_messages), GC10_CHANNEL_ID, sync_state, message_store)

        conn = get_connection(db_path)
        try:
            rows = {
                row["id"]: dict(row)
                for row in conn.execute(
                    "SELECT id, posted_at, edited_at, deleted_at, is_deleted, is_bot, is_system, body_raw "
                    "FROM messages WHERE channel_id = ?",
                    (GC10_CHANNEL_ID,),
                )
            }
        finally:
            conn.close()

    total_count = len(rows)

    edit_row = rows["gc10-edit-1"]
    edit_posted_at_preserved = edit_row["posted_at"] == "2026-09-01T09:03:00Z"
    edit_content_updated = (
        edit_row["body_raw"] == "Finished the notes after all."
        and edit_row["edited_at"] == "2026-09-02T10:05:00Z"
    )

    del_row = rows["gc10-del-1"]
    delete_handled = (
        bool(del_row["is_deleted"])
        and del_row["deleted_at"] == "2026-09-02T10:06:00Z"
        and del_row["posted_at"] == "2026-09-01T09:04:00Z"
    )

    actual_bot_flags = {message_id: bool(row["is_bot"]) for message_id, row in rows.items()}
    expected_bot_flags = {message_id: message_id in _GC10_BOT_IDS for message_id in rows}

    actual_system_flags = {message_id: bool(row["is_system"]) for message_id, row in rows.items()}
    expected_system_flags = {message_id: message_id in _GC10_SYSTEM_IDS for message_id in rows}

    return [
        MetricResult(
            metric_id="GC10-message-count",
            name="total stored message count across both delta runs, no duplicates",
            measured=total_count,
            target=7,
            comparator_name="equals",
            passed=equals(total_count, 7),
            detail=(
                f"run1 ingested={result1.messages_ingested} run2 ingested={result2.messages_ingested} "
                "(5 ids from run 1 + 2 new ids from run 2; the resent edit/delete reuse existing ids)"
            ),
        ),
        MetricResult(
            metric_id="GC10-edit-posted-at-preserved",
            name="edited message keeps its original posted_at across the second delta run",
            measured=edit_posted_at_preserved,
            target=True,
            comparator_name="equals",
            passed=equals(edit_posted_at_preserved, True),
            detail=f"actual posted_at={edit_row['posted_at']!r}",
        ),
        MetricResult(
            metric_id="GC10-edit-content-updated",
            name="edited message's body and edited_at are updated by the second delta run",
            measured=edit_content_updated,
            target=True,
            comparator_name="equals",
            passed=equals(edit_content_updated, True),
            detail=f"actual body={edit_row['body_raw']!r} edited_at={edit_row['edited_at']!r}",
        ),
        MetricResult(
            metric_id="GC10-delete-handled",
            name="deleted message is flagged deleted, deleted_at is set, posted_at is unchanged",
            measured=delete_handled,
            target=True,
            comparator_name="equals",
            passed=equals(delete_handled, True),
            detail=(
                f"is_deleted={bool(del_row['is_deleted'])} deleted_at={del_row['deleted_at']!r} "
                f"posted_at={del_row['posted_at']!r}"
            ),
        ),
        MetricResult(
            metric_id="GC10-bot-flags-correct",
            name="is_bot is correct for every message introduced across both delta runs",
            measured=actual_bot_flags,
            target=expected_bot_flags,
            comparator_name="equals",
            passed=equals(actual_bot_flags, expected_bot_flags),
            detail="gc10-bot-1 (run 1) and gc10-bot-2 (run 2) True, every other message False",
        ),
        MetricResult(
            metric_id="GC10-system-flags-correct",
            name="is_system is correct for every message introduced across both delta runs",
            measured=actual_system_flags,
            target=expected_system_flags,
            comparator_name="equals",
            passed=equals(actual_system_flags, expected_system_flags),
            detail="gc10-sys-1 (run 1) and gc10-sys-2 (run 2) True, every other message False",
        ),
    ]


def register(registry: GoldenCaseRegistry) -> None:
    registry.register(
        GoldenCase(
            case_id="GC5",
            description="Scope gate hard zero: out-of-scope channel and chats contribute nothing (CHN-12)",
            measure_fn=_measure_gc5,
        )
    )
    registry.register(
        GoldenCase(
            case_id="GC10",
            description="Ingest correctness across two delta runs: edit, delete, bot, system (CHN-12)",
            measure_fn=_measure_gc10,
        )
    )
