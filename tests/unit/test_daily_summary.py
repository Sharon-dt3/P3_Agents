"""
CHN-13's own acceptance test: a seeded day produces a summary in which
every factual line resolves to a real message, and a channel with no
traffic produces an honest empty summary.

Follows the same seeding style test_participation_ledger.py already
uses (a make_config()/_message() pair, classifications recorded
directly via ClassificationStore rather than run through the real
CHN-08/CHN-09 pipeline) since this module's own job starts downstream
of that pipeline: it reads whatever classifications.label already says.
"""

from __future__ import annotations

import json
from datetime import date, time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.llm.gateway import LLMResponse
from p1.participation.ledger import EXCLUDED, NO_MESSAGE, POSTED_NO_UPDATE
from p1.prompts import PromptRegistry
from p1.reporting.daily_summary import (
    DAILY_SUMMARY_CAPABILITY,
    generate_and_persist_daily_summary,
    generate_daily_summary,
)
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore
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
        "permalink": "https://teams.microsoft.com/l/message/c1/m1",
    }
    defaults.update(overrides)
    return TeamsMessage(**defaults)


def _seed_fact(db_path, *, message_id, author_id, label, body, permalink="https://example/msg", **msg_overrides):
    message = _message(id=message_id, author_id=author_id, body=body, permalink=permalink, **msg_overrides)
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id=message_id, label=label, method="model", confidence=0.9)
    return message


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


class FakeGateway:
    """Stand-in for LLMGateway: returns canned tool-call JSON in order,
    and records every prompt it was actually called with."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0
        self.prompts = []

    def generate(self, prompt, **kwargs):
        self.calls += 1
        self.prompts.append(prompt)
        text = self._texts.pop(0)
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def _draft(*lines) -> str:
    return json.dumps({"lines": [dict(l) for l in lines]})


def _line(message_id, text, quote=None) -> dict:
    return {"message_id": message_id, "text": text, "quote": quote}


# --- a fully seeded day --------------------------------------------------

def test_what_moved_blockers_decisions_and_questions_are_grounded_with_permalinks(db_path):
    _seed_fact(
        db_path, message_id="m-update", author_id="alice", label="update",
        body="Deployed the export job to staging.", permalink="https://t/m-update",
    )
    _seed_fact(
        db_path, message_id="m-blocker", author_id="bob", label="blocker",
        body="Blocked on the staging credentials rotating.", permalink="https://t/m-blocker",
    )
    _seed_fact(
        db_path, message_id="m-decision", author_id="carol", label="decision",
        body="Decided to ship behind a feature flag.", permalink="https://t/m-decision",
    )
    _seed_fact(
        db_path, message_id="m-question", author_id="alice", label="question",
        body="Should we roll this out to all channels at once?", permalink="https://t/m-question",
    )

    gateway = FakeGateway([
        _draft(_line("m-update", "Alice deployed the export job to staging.")),
        _draft(_line("m-blocker", "Bob is blocked on the staging credentials rotating.")),
        _draft(_line("m-decision", "Carol decided to ship behind a feature flag.")),
        _draft(_line("m-question", "Alice is asking whether to roll this out to all channels at once.")),
    ])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert [line.message_id for line in result.section_lines["what_moved"]] == ["m-update"]
    assert [line.message_id for line in result.section_lines["blockers"]] == ["m-blocker"]
    assert [line.message_id for line in result.section_lines["decisions"]] == ["m-decision"]
    assert [line.message_id for line in result.section_lines["questions"]] == ["m-question"]
    assert gateway.calls == 4

    for permalink in ("https://t/m-update", "https://t/m-blocker", "https://t/m-decision", "https://t/m-question"):
        assert permalink in result.content


def test_a_message_body_is_interpolated_verbatim_into_the_rendered_prompt(db_path):
    _seed_fact(
        db_path, message_id="m-update", author_id="alice", label="update",
        body="Deployed the export job to staging.",
    )
    gateway = FakeGateway([_draft(_line("m-update", "Alice deployed the export job."))])

    generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert "Deployed the export job to staging." in gateway.prompts[0]
    assert "what moved" in gateway.prompts[0]


# --- honest empty summary -------------------------------------------------

def test_channel_with_no_traffic_produces_an_honest_empty_summary_with_no_model_calls(db_path):
    gateway = FakeGateway([])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert gateway.calls == 0
    for section in ("what_moved", "blockers", "decisions", "questions"):
        assert result.section_lines[section] == []
    assert "No updates were posted today." in result.content
    assert "No blockers were raised today." in result.content
    assert "No decisions were taken today." in result.content
    assert "No questions are awaiting an answer today." in result.content
    # a silent channel is still a fully populated participation section --
    # "empty" here only ever describes the four content sections.
    assert "no message posted" in result.content


def test_a_channel_where_only_chatter_was_posted_still_makes_no_model_calls(db_path):
    """Chatter and noise are never facts for this digest -- a busy but
    contentless channel is exactly as honestly empty as a silent one."""
    _seed_fact(db_path, message_id="m-chatter", author_id="alice", label="chatter", body="Sounds good, thanks!")

    gateway = FakeGateway([])
    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert gateway.calls == 0
    assert result.section_lines["what_moved"] == []


# --- questions still awaiting an answer -----------------------------------

def test_a_question_with_no_reply_is_still_awaiting_an_answer(db_path):
    _seed_fact(
        db_path, message_id="m-q1", author_id="alice", label="question",
        body="Should we roll this out today?",
    )
    gateway = FakeGateway([_draft(_line("m-q1", "Alice is asking whether to roll this out today."))])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert [line.message_id for line in result.section_lines["questions"]] == ["m-q1"]


def test_a_question_with_a_reply_is_no_longer_awaiting_an_answer(db_path):
    _seed_fact(
        db_path, message_id="m-q2", author_id="alice", label="question",
        body="Should we roll this out today?",
    )
    # any non-deleted reply at all counts as addressed -- see
    # _answered_question_ids's own docstring for why this doesn't try
    # to judge whether the reply substantively answers it.
    reply = _message(
        id="m-q2-reply", author_id="bob", body="Yes, go ahead.",
        thread_root_id="m-q2", posted_at="2025-06-02T09:45:00+05:30",
    )
    MessageStore(db_path).upsert_messages([reply])

    gateway = FakeGateway([])
    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert result.section_lines["questions"] == []
    assert gateway.calls == 0


def test_a_question_answered_only_by_a_deleted_reply_is_still_awaiting_an_answer(db_path):
    _seed_fact(
        db_path, message_id="m-q3", author_id="alice", label="question",
        body="Should we roll this out today?",
    )
    reply = _message(
        id="m-q3-reply", author_id="bob", body="Yes, go ahead.",
        thread_root_id="m-q3", posted_at="2025-06-02T09:45:00+05:30", is_deleted=True,
    )
    MessageStore(db_path).upsert_messages([reply])

    gateway = FakeGateway([_draft(_line("m-q3", "Alice is asking whether to roll this out today."))])
    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert [line.message_id for line in result.section_lines["questions"]] == ["m-q3"]


# --- grounding: only this section's own facts can ground a line ----------

def test_a_line_claiming_a_real_but_unrelated_message_id_is_dropped_not_kept(db_path):
    """The message_lookup handed to the grounding kernel is scoped to
    just this section's own facts -- a message_id that is real
    elsewhere in the store (here: bob's blocker) must not let a
    what_moved line ground itself on content it was never given."""
    _seed_fact(
        db_path, message_id="m-update", author_id="alice", label="update",
        body="Deployed the export job to staging.",
    )
    _seed_fact(
        db_path, message_id="m-blocker", author_id="bob", label="blocker",
        body="Blocked on the staging credentials rotating.",
    )

    gateway = FakeGateway([
        # what_moved's own model call insists, across every retry
        # attempt (ground_with_retry's default max_attempts=3), on
        # bob's blocker message id -- real in the store, but never one
        # of what_moved's own facts, so it can never ground here no
        # matter how the retry is phrased.
        _draft(_line("m-blocker", "Something happened.")),
        _draft(_line("m-blocker", "Something happened again.")),
        _draft(_line("m-blocker", "Something happened yet again.")),
        # blockers' own single call, correctly claiming its own fact.
        _draft(_line("m-blocker", "Bob is blocked on the staging credentials rotating.")),
    ])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert gateway.calls == 4
    assert result.section_lines["what_moved"] == []
    assert result.dropped["what_moved"][0].reason == "unresolvable_message_id"
    assert [line.message_id for line in result.section_lines["blockers"]] == ["m-blocker"]


def test_a_near_miss_quote_is_dropped_and_retried(db_path):
    _seed_fact(
        db_path, message_id="m-update", author_id="alice", label="update",
        body="Deployed the export job to staging.",
    )
    gateway = FakeGateway([
        _draft(_line("m-update", "Alice said this.", quote="Deployed the export job to production.")),
        _draft(_line("m-update", "Alice said this.", quote="Deployed the export job to staging.")),
    ])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert gateway.calls == 2
    assert [line.message_id for line in result.section_lines["what_moved"]] == ["m-update"]


def test_a_deleted_message_never_becomes_a_fact_even_if_classified(db_path):
    _seed_fact(
        db_path, message_id="m-deleted", author_id="alice", label="update",
        body="This was retracted.", is_deleted=True,
    )
    gateway = FakeGateway([])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert result.section_lines["what_moved"] == []
    assert gateway.calls == 0


def test_a_message_with_no_permalink_never_becomes_a_fact(db_path):
    """Every factual line carries a message permalink -- a message with
    none can never satisfy that, so it is never even offered to the
    model in the first place."""
    _seed_fact(
        db_path, message_id="m-nolink", author_id="alice", label="update",
        body="Deployed the export job.", permalink=None,
    )
    gateway = FakeGateway([])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert result.section_lines["what_moved"] == []
    assert gateway.calls == 0


def test_a_non_roster_authors_message_never_becomes_a_fact(db_path):
    conn = get_connection(db_path)
    conn.execute("INSERT INTO members (id, display_name) VALUES ('not-on-roster', 'Guest')")
    conn.commit()
    conn.close()

    _seed_fact(
        db_path, message_id="m-outsider", author_id="not-on-roster", label="update",
        body="Deployed the export job.",
    )
    gateway = FakeGateway([])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert result.section_lines["what_moved"] == []
    assert gateway.calls == 0


# --- participation section -------------------------------------------------

def test_participation_uses_chn14s_exact_three_state_wording(db_path):
    gateway = FakeGateway([])
    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    by_member = {r.member_id: r.state for r in result.participation}
    assert by_member["dave"] == EXCLUDED
    assert by_member["bob"] == NO_MESSAGE

    assert "dave — excluded - on the exceptions list" in result.content
    assert "bob — no message posted" in result.content


def test_a_member_who_posted_only_chatter_is_posted_no_update_not_silent(db_path):
    _seed_fact(db_path, message_id="m-chatter", author_id="carol", label="chatter", body="Thanks all!")

    gateway = FakeGateway([])
    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    by_member = {r.member_id: r.state for r in result.participation}
    assert by_member["carol"] == POSTED_NO_UPDATE
    assert "carol — posted, but no update" in result.content


def test_participation_line_reads_every_roster_member_contributed_when_nobody_is_a_non_responder(db_path):
    for member_id in ("alice", "bob", "carol", "dave"):
        _seed_fact(db_path, message_id=f"m-{member_id}", author_id=member_id, label="update", body="Update text here.")

    gateway = FakeGateway([_draft(*[
        _line(f"m-{m}", f"{m} posted an update.") for m in ("alice", "bob", "carol", "dave")
    ])])

    result = generate_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    assert result.participation == []
    assert "Every roster member contributed an update today." in result.content


# --- persistence -----------------------------------------------------------

def test_generate_and_persist_upserts_by_idempotency_key_not_duplicate_rows(db_path):
    gateway = FakeGateway([])
    generate_and_persist_daily_summary(CHANNEL_ID, DAY, make_config(), gateway, db_path=db_path)

    _seed_fact(
        db_path, message_id="m-update", author_id="alice", label="update",
        body="Deployed the export job to staging.",
    )
    gateway2 = FakeGateway([_draft(_line("m-update", "Alice deployed the export job to staging."))])
    generate_and_persist_daily_summary(CHANNEL_ID, DAY, make_config(), gateway2, db_path=db_path)

    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT content FROM digests WHERE channel_id = ? AND date = ? AND type = 'daily'",
            (CHANNEL_ID, DAY.isoformat()),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 1
    assert "Alice deployed the export job to staging." in rows[0]["content"]


def test_digest_store_get_by_idempotency_key(db_path):
    key = f"{CHANNEL_ID}:{DAY.isoformat()}:daily"
    DigestStore(db_path).record(
        channel_id=CHANNEL_ID, date=DAY.isoformat(), type="daily", content="hello", idempotency_key=key,
    )
    row = DigestStore(db_path).get_by_idempotency_key(key)
    assert row["content"] == "hello"
    assert row["published_at"] is None


# --- prompt capability -------------------------------------------------

def test_daily_summary_capability_prompt_is_loaded_from_the_registry():
    prompt = PromptRegistry().get(DAILY_SUMMARY_CAPABILITY)
    assert prompt.capability == "chn13_daily_summary"
    for placeholder in ("{section_label}", "{facts_block}", "{feedback_block}"):
        assert placeholder in prompt.text
