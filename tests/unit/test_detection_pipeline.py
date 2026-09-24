from datetime import time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.detection.pipeline import classify_and_persist
from p1.llm.gateway import LLMResponse
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

TZ = "Asia/Colombo"


class FakeGateway:
    """Stand-in for LLMGateway: returns canned tool-call JSON in order.
    An empty texts list means the model must never be called at all --
    popping from it would raise IndexError, which is exactly the
    failure a rule-settled message reaching the model should produce."""

    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        text = self._texts.pop(0)
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def make_config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": "c1",
        "display_name": "Channel One",
        "allowlisted": True,
        "roster": ["alice", "bob"],
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
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def make_message(**overrides) -> TeamsMessage:
    defaults = {
        "id": "msg-1",
        "channel_id": "c1",
        "author_id": "alice",
        "posted_at": "2025-06-02T09:30:00+05:30",  # a Monday, within the default window
        "body": "Finished the auth flow, running the tests now.",
    }
    defaults.update(overrides)
    return TeamsMessage(**defaults)


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'Channel One', 1)")
    conn.execute("INSERT INTO members (id, display_name) VALUES ('alice', 'Alice')")
    conn.execute("INSERT INTO members (id, display_name) VALUES ('bob', 'Bob')")
    conn.commit()
    conn.close()
    return path


def _seed_messages(db_path, messages) -> None:
    MessageStore(db_path).upsert_messages(messages)


def _classification_rows(db_path) -> dict:
    conn = get_connection(db_path)
    try:
        return {row["message_id"]: dict(row) for row in conn.execute("SELECT * FROM classifications")}
    finally:
        conn.close()


def test_rule_settled_message_never_reaches_the_model(db_path):
    message = make_message(is_deleted=True)
    _seed_messages(db_path, [message])
    gateway = FakeGateway([])

    outcomes = classify_and_persist([message], make_config(), gateway, db_path=db_path)

    assert gateway.calls == 0
    assert outcomes[0].method == "rule"
    assert outcomes[0].rule_name == "deleted_message"


def test_rule_settled_message_is_persisted_with_null_confidence(db_path):
    message = make_message(is_deleted=True)
    _seed_messages(db_path, [message])
    gateway = FakeGateway([])

    classify_and_persist([message], make_config(), gateway, db_path=db_path)

    row = _classification_rows(db_path)[message.id]
    assert row["label"] == "noise"
    assert row["method"] == "rule"
    assert row["rule_name"] == "deleted_message"
    assert row["confidence"] is None


def test_rule_settled_outcome_is_never_uncertain(db_path):
    message = make_message(is_deleted=True)
    _seed_messages(db_path, [message])
    gateway = FakeGateway([])

    outcomes = classify_and_persist([message], make_config(), gateway, db_path=db_path)
    assert outcomes[0].uncertain is False


def test_model_settled_non_noise_label_is_persisted(db_path):
    message = make_message(body="Finished the auth flow, running the tests now.")
    _seed_messages(db_path, [message])
    gateway = FakeGateway(['{"label": "update", "confidence": 0.92}'])

    outcomes = classify_and_persist([message], make_config(), gateway, db_path=db_path)

    assert gateway.calls == 1
    assert outcomes[0].persisted is True
    row = _classification_rows(db_path)[message.id]
    assert row["label"] == "update"
    assert row["method"] == "model"
    assert row["rule_name"] is None
    assert row["confidence"] == 0.92


def test_model_noise_is_discarded_not_persisted(db_path):
    """CHN-09's 'noise is discarded, not stored' -- distinct from a
    rule's noise verdict, which IS stored (see detection/rules.py and
    detection/pipeline.py's module docstring for the asymmetry)."""
    message = make_message(body="asdkjfh asdkjfh qqweoiuqwe garbled")
    _seed_messages(db_path, [message])
    gateway = FakeGateway(['{"label": "noise", "confidence": 0.8}'])

    outcomes = classify_and_persist([message], make_config(), gateway, db_path=db_path)

    assert outcomes[0].persisted is False
    assert outcomes[0].label == "noise"
    assert message.id not in _classification_rows(db_path)


def test_uncertain_flag_propagates_from_low_confidence_model_result(db_path):
    message = make_message(body="Not totally sure what this means honestly")
    _seed_messages(db_path, [message])
    gateway = FakeGateway(['{"label": "chatter", "confidence": 0.4}'])

    outcomes = classify_and_persist([message], make_config(), gateway, db_path=db_path)

    assert outcomes[0].uncertain is True
    # Low confidence is surfaced, not withheld -- it's still a real,
    # non-noise judgement and is stored like any other.
    assert outcomes[0].persisted is True


def test_returns_one_outcome_per_message_preserving_order(db_path):
    deleted = make_message(id="m1", is_deleted=True)
    eligible = make_message(id="m2", body="Finished the auth flow, running the tests now.")
    _seed_messages(db_path, [deleted, eligible])
    gateway = FakeGateway(['{"label": "update", "confidence": 0.9}'])

    outcomes = classify_and_persist([deleted, eligible], make_config(), gateway, db_path=db_path)

    assert [o.message_id for o in outcomes] == ["m1", "m2"]
    assert gateway.calls == 1  # only the eligible message reached the model


# --- reuse_model_verdicts: the live runners' every-tick re-run (2026-09-24) ---------------

def _backdate_classification(db_path, message_id, when="2020-01-01 00:00:00") -> None:
    conn = get_connection(db_path)
    conn.execute("UPDATE classifications SET created_at = ? WHERE message_id = ?", (when, message_id))
    conn.commit()
    conn.close()


def test_default_still_rejudges_every_message_every_run(db_path):
    """Off by default: one-shot scripts, the eval harness and prompt-version
    comparisons all rely on a fresh judgement each run."""
    message = make_message()
    _seed_messages(db_path, [message])
    gateway = FakeGateway(['{"label": "update", "confidence": 0.9}', '{"label": "question", "confidence": 0.8}'])

    classify_and_persist([message], make_config(), gateway, db_path=db_path)
    classify_and_persist([message], make_config(), gateway, db_path=db_path)

    assert gateway.calls == 2
    assert _classification_rows(db_path)[message.id]["label"] == "question"


def test_a_message_the_model_already_judged_is_not_sent_to_the_model_again(db_path):
    message = make_message()
    _seed_messages(db_path, [message])
    first = FakeGateway(['{"label": "update", "confidence": 0.9}'])
    classify_and_persist([message], make_config(), first, db_path=db_path, reuse_model_verdicts=True)
    assert first.calls == 1

    second = FakeGateway([])  # any call would raise IndexError
    outcomes = classify_and_persist([message], make_config(), second, db_path=db_path, reuse_model_verdicts=True)

    assert second.calls == 0
    assert (outcomes[0].label, outcomes[0].method, outcomes[0].confidence) == ("update", "model", 0.9)
    assert _classification_rows(db_path)[message.id]["label"] == "update"


def test_an_edit_after_the_verdict_is_rejudged_and_then_stops_being_rejudged(db_path):
    message = make_message(body="Should we ship on Friday?")
    _seed_messages(db_path, [message])
    classify_and_persist(
        [message], make_config(), FakeGateway(['{"label": "question", "confidence": 0.9}']),
        db_path=db_path, reuse_model_verdicts=True,
    )
    _backdate_classification(db_path, message.id, "2026-06-02 01:00:00")

    edited = make_message(body="Finished the auth flow, tests pass.", edited_at="2026-06-02T02:00:00Z")
    rejudge = FakeGateway(['{"label": "update", "confidence": 0.95}'])
    outcomes = classify_and_persist([edited], make_config(), rejudge, db_path=db_path, reuse_model_verdicts=True)
    assert rejudge.calls == 1
    assert outcomes[0].label == "update"

    # The re-record refreshed the row's timestamp, so the SAME edit is not
    # re-judged again on every later tick.
    again = FakeGateway([])
    classify_and_persist([edited], make_config(), again, db_path=db_path, reuse_model_verdicts=True)
    assert again.calls == 0


def test_rules_are_still_reevaluated_for_a_message_that_has_a_stored_model_verdict(db_path):
    """A config change can newly settle a message; reuse must never freeze
    that out. Here the message was model-judged, then the roster changes
    so a rule now excludes it."""
    message = make_message()
    _seed_messages(db_path, [message])
    classify_and_persist(
        [message], make_config(), FakeGateway(['{"label": "update", "confidence": 0.9}']),
        db_path=db_path, reuse_model_verdicts=True,
    )

    outcomes = classify_and_persist(
        [message], make_config(roster=["someone-else"]), FakeGateway([]),
        db_path=db_path, reuse_model_verdicts=True,
    )

    assert (outcomes[0].method, outcomes[0].rule_name) == ("rule", "not_on_roster")
    assert _classification_rows(db_path)[message.id]["rule_name"] == "not_on_roster"
