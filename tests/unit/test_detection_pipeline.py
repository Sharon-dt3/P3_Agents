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
