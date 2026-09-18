"""
CHN-22's own acceptance test: "Every nudge, escalation and digest is a
row you can show on camera before anything is ever sent." LogPublisher
is what makes that literally true for the mock path -- every call
appends one JSON line to disk, immediately, so the file itself is the
thing you show on camera.
"""

from __future__ import annotations

import json

from p1.adapters.teams_publisher_mock import CHANNEL_POST, DIRECT_MESSAGE, LogPublisher


def test_post_channel_message_appends_one_json_line(tmp_path):
    log_path = tmp_path / "outbound.jsonl"
    publisher = LogPublisher(log_path=log_path)

    result = publisher.post_channel_message("c1", "hello channel")

    assert result["ok"] is True
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["action_type"] == CHANNEL_POST
    assert row["target"] == "c1"
    assert row["content"] == "hello channel"
    assert "logged_at" in row


def test_post_direct_message_appends_one_json_line(tmp_path):
    log_path = tmp_path / "outbound.jsonl"
    publisher = LogPublisher(log_path=log_path)

    publisher.post_direct_message("bob", "hi bob")

    row = json.loads(log_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["action_type"] == DIRECT_MESSAGE
    assert row["target"] == "bob"
    assert row["content"] == "hi bob"


def test_multiple_calls_append_rather_than_overwrite(tmp_path):
    log_path = tmp_path / "outbound.jsonl"
    publisher = LogPublisher(log_path=log_path)

    publisher.post_channel_message("c1", "first")
    publisher.post_direct_message("bob", "second")
    publisher.post_channel_message("c1", "third")

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [row["content"] for row in rows] == ["first", "second", "third"]


def test_a_new_instance_pointed_at_the_same_path_still_appends(tmp_path):
    """The log is a file, not in-memory state -- a fresh LogPublisher
    (e.g. a new job run) pointed at the same path picks up where the
    last one left off, rather than starting a new file."""
    log_path = tmp_path / "outbound.jsonl"
    LogPublisher(log_path=log_path).post_channel_message("c1", "run one")

    LogPublisher(log_path=log_path).post_channel_message("c1", "run two")

    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert [row["content"] for row in rows] == ["run one", "run two"]


def test_read_log_returns_every_row_in_order(tmp_path):
    log_path = tmp_path / "outbound.jsonl"
    publisher = LogPublisher(log_path=log_path)
    publisher.post_channel_message("c1", "first")
    publisher.post_direct_message("bob", "second")

    rows = publisher.read_log()

    assert [row["content"] for row in rows] == ["first", "second"]


def test_read_log_on_a_path_that_does_not_exist_yet_is_an_empty_list(tmp_path):
    publisher = LogPublisher(log_path=tmp_path / "never_written.jsonl")

    assert publisher.read_log() == []


def test_creates_parent_directories_that_do_not_exist_yet(tmp_path):
    log_path = tmp_path / "nested" / "dirs" / "outbound.jsonl"

    LogPublisher(log_path=log_path).post_channel_message("c1", "hello")

    assert log_path.exists()
