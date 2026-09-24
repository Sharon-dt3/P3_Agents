"""
CHN-14's own acceptance test: the chatter-only member is never reported
as having posted no message, and the on-leave member is never reported
as silent -- proved directly against p1.reporting.participation_rendering,
not just implicitly through the full daily digest (test_daily_summary.py
already exercises this end to end; this file pins down the rendering
contract on its own, so a future digest-assembly refactor can't quietly
break it without a fast, focused test catching it).

Follows the same make_config()/_message()/db_path fixture pattern
test_participation_ledger.py already uses, since this module renders
whatever build_ledger actually returns.
"""

from __future__ import annotations

from datetime import date, time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.participation.ledger import (
    EXCLUDED,
    NO_MESSAGE,
    POSTED_NO_UPDATE,
    ParticipationRecord,
    build_ledger,
)
from p1.reporting.participation_rendering import (
    PARTICIPATION_WORDING,
    render_participation_lines,
    render_participation_section,
)
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

TZ = "Asia/Colombo"
DAY = date(2025, 6, 2)  # a Monday
CHANNEL_ID = "c1"


def make_config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID,
        "display_name": "Channel One",
        "allowlisted": True,
        "roster": ["alice", "bob", "carol", "dave"],
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": TZ,
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "length_floor": 10,
        "count_thread_replies": True,
        "ignore_bots": True,
        "daily_digest_time": time(11, 30),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
        "exceptions": [{"member_id": "dave", "reason": "On leave"}],
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def _message(**overrides) -> TeamsMessage:
    defaults = {
        "id": "m1",
        "channel_id": CHANNEL_ID,
        "author_id": "alice",
        "posted_at": "2025-06-02T09:30:00+05:30",
        "body": "Finished the thing, running the tests now.",
    }
    defaults.update(overrides)
    return TeamsMessage(**defaults)


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'Channel One', 1)")
    for member_id in ("alice", "bob", "carol", "dave"):
        conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
    conn.commit()
    conn.close()
    return path


# --- the exact wording contract --------------------------------------------

def test_wording_map_is_exactly_the_three_specified_phrases_and_nothing_else():
    """A pinned snapshot of the wording map itself: the WBS row's own
    wording is a design decision, not a formatting detail, so a future
    edit that quietly rephrases one of these (adds an adjective, a
    count, a judgment) fails this test immediately rather than only
    showing up as a diff in a generated digest."""
    assert PARTICIPATION_WORDING == {
        NO_MESSAGE: "no message posted",
        POSTED_NO_UPDATE: "posted, but no update",
        EXCLUDED: "excluded - on the exceptions list",
    }


def test_each_state_renders_to_its_exact_wording_with_no_extra_text():
    records = [
        ParticipationRecord(channel_id=CHANNEL_ID, member_id="a", date=DAY.isoformat(), state=NO_MESSAGE, evidence_message_ids=()),
        ParticipationRecord(channel_id=CHANNEL_ID, member_id="b", date=DAY.isoformat(), state=POSTED_NO_UPDATE, evidence_message_ids=("m1",)),
        ParticipationRecord(channel_id=CHANNEL_ID, member_id="c", date=DAY.isoformat(), state=EXCLUDED, evidence_message_ids=()),
    ]

    lines = render_participation_lines(records)

    assert lines == [
        "a — no message posted",
        "b — posted, but no update",
        "c — excluded - on the exceptions list",
    ]


# --- CHN-14's own named acceptance test -------------------------------------

def test_the_chatter_only_member_is_never_reported_as_having_posted_no_message(db_path):
    message = _message(id="m-chatter", author_id="bob", body="Thanks all, sounds good!")
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id="m-chatter", label="chatter", method="model", confidence=0.9)

    records = build_ledger(CHANNEL_ID, DAY, make_config(), db_path=db_path)
    lines = render_participation_lines(records, db_path=db_path)

    bob_line = next(line for line in lines if line.startswith("bob"))
    assert bob_line == "bob — posted, but no update"
    assert "no message posted" not in bob_line


def test_the_on_leave_member_is_never_reported_as_silent(db_path):
    # dave has zero messages today and is on the exceptions list.
    records = build_ledger(CHANNEL_ID, DAY, make_config(), db_path=db_path)
    lines = render_participation_lines(records, db_path=db_path)

    dave_line = next(line for line in lines if line.startswith("dave"))
    assert dave_line == "dave — excluded - on the exceptions list"
    assert "no message posted" not in dave_line


# --- no inferred reasons ----------------------------------------------------

def test_the_configured_exception_reason_never_appears_in_the_rendered_output(db_path):
    """dave's exception reason is "On leave" -- ParticipationRecord never
    carries it (see p1.participation.ledger.ParticipationRecord's own
    fields), so it is structurally impossible for it to leak into the
    rendered line, not merely something this module promises not to
    do."""
    records = build_ledger(CHANNEL_ID, DAY, make_config(), db_path=db_path)
    lines = render_participation_lines(records, db_path=db_path)

    assert not any("leave" in line.lower() for line in lines)
    assert not any("On leave" in line for line in lines)


def test_a_different_exception_reason_produces_byte_identical_wording(db_path):
    """The rendered line for an excluded member must not vary with the
    configured reason text -- proving the reason genuinely never
    reaches the renderer, rather than merely being absent from this
    particular reason string."""
    records_a = build_ledger(
        CHANNEL_ID, DAY, make_config(exceptions=[{"member_id": "dave", "reason": "On leave"}]), db_path=db_path,
    )
    records_b = build_ledger(
        CHANNEL_ID, DAY, make_config(exceptions=[{"member_id": "dave", "reason": "Sabbatical until further notice"}]),
        db_path=db_path,
    )

    assert render_participation_lines(records_a, db_path=db_path) == render_participation_lines(records_b, db_path=db_path)


# --- no ranking of people ----------------------------------------------------

def test_rendering_preserves_the_ledgers_own_order_never_resorting_by_state(db_path):
    """build_ledger already sorts by member_id (test_ledger_is_sorted_
    by_member_id in test_participation_ledger.py). This module must
    never re-sort by state, severity, or anything else -- a mixed batch
    of every state, fed in deliberately out of member_id order, comes
    back rendered in exactly the order given."""
    records = [
        ParticipationRecord(channel_id=CHANNEL_ID, member_id="zack", date=DAY.isoformat(), state=EXCLUDED, evidence_message_ids=()),
        ParticipationRecord(channel_id=CHANNEL_ID, member_id="amy", date=DAY.isoformat(), state=NO_MESSAGE, evidence_message_ids=()),
        ParticipationRecord(channel_id=CHANNEL_ID, member_id="mo", date=DAY.isoformat(), state=POSTED_NO_UPDATE, evidence_message_ids=()),
    ]

    lines = render_participation_lines(records)

    assert [line.split(" — ")[0] for line in lines] == ["zack", "amy", "mo"]


# --- the full section block -------------------------------------------------

def test_render_participation_section_lists_every_non_responder_under_a_heading(db_path):
    records = build_ledger(CHANNEL_ID, DAY, make_config(), db_path=db_path)
    section = render_participation_section(records, db_path=db_path)

    assert section[0] == "## Participation"
    assert section[-1] == ""
    assert "- dave — excluded - on the exceptions list" in section
    assert "- bob — no message posted" in section


def test_render_participation_section_with_no_non_responders_reads_the_honest_fallback_line():
    section = render_participation_section([])

    assert section == [
        "## Participation",
        "- Every roster member contributed an update today.",
        "",
    ]
