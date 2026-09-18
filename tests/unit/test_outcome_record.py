"""
CHN-26's own acceptance test: "a second process reconstructs the day's
updates and participation from the record with no access to the
message store." Every test that reads a record back does so through
read_outcome() alone -- several of them delete the sqlite db entirely
between writing and reading, so this is a structural proof (reading
literally cannot reach the message store, because it's gone), not
merely "this test happened not to call it."

The realistic fixture reuses test_daily_summary.py's own seeding style
and FakeGateway, since build_outcome_record() takes the real
DailySummaryResult CHN-13's own pipeline produces -- never a
hand-built stand-in for it.
"""

from __future__ import annotations

import json
from datetime import date, time

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.contracts.outcome_record import (
    SCHEMA_VERSION,
    build_outcome_record,
    read_outcome,
    schema_version,
    write_outcome,
)
from p1.llm.gateway import LLMResponse
from p1.reporting.daily_summary import generate_daily_summary
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

CHANNEL_ID = "19:proj-alpha@thread.tacv2"  # deliberately has ':' and '@' -- exercises _slug()
DAY = date(2025, 6, 2)


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID, "display_name": "Project Alpha", "allowlisted": True,
        "roster": ["alice", "bob", "carol", "dave"],
        "update_window_start": time(9, 0), "update_window_end": time(11, 0),
        "timezone": "Asia/Colombo", "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "daily_digest_time": time(11, 30), "weekly_digest_day": "Fri", "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice", "exceptions": [{"member_id": "dave", "reason": "On leave"}],
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


class FakeGateway:
    def __init__(self, texts):
        self._texts = list(texts)
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        return LLMResponse(
            text=self._texts.pop(0), provider="fake", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def _draft(message_id, text, quote=None) -> str:
    return json.dumps({"lines": [{"message_id": message_id, "text": text, "quote": quote}]})


def _seed_db(db_path) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute(
        "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'Project Alpha', 1)", (CHANNEL_ID,)
    )
    for member_id in ("alice", "bob", "carol", "dave"):
        conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
    conn.commit()
    conn.close()


def _seed_fact(db_path, *, message_id, author_id, label, body) -> None:
    MessageStore(db_path).upsert_messages(
        [TeamsMessage(id=message_id, channel_id=CHANNEL_ID, author_id=author_id,
                      posted_at=f"{DAY.isoformat()}T09:30:00+05:30", body=body,
                      permalink=f"https://t/{message_id}")]
    )
    ClassificationStore(db_path).record(message_id=message_id, label=label, method="model", confidence=0.9)


def test_schema_version_matches_the_module_constant():
    assert schema_version() == SCHEMA_VERSION == "1.0"


def test_build_and_write_then_read_round_trips_with_no_db_access_in_between(tmp_path):
    db_path = tmp_path / "test.db"
    outcomes_dir = tmp_path / "outcomes"
    _seed_db(db_path)
    _seed_fact(db_path, message_id="m-update", author_id="alice", label="update", body="Deployed the export job.")
    _seed_fact(db_path, message_id="m-blocker", author_id="bob", label="blocker", body="Blocked on creds rotating.")
    # carol posts nothing -> no_message; dave is excluded (on leave)

    gateway = FakeGateway([
        _draft("m-update", "Alice deployed the export job to staging.", quote="Deployed the export job."),
        _draft("m-blocker", "Bob is blocked on creds rotating.", quote="Blocked on creds rotating."),
    ])
    config = _config()
    result = generate_daily_summary(CHANNEL_ID, DAY, config, gateway, db_path=db_path)
    record = build_outcome_record(result, config)
    path = write_outcome(record, output_dir=outcomes_dir)
    assert path.exists()

    # Simulate "a second process with no access to the message store":
    # the db is gone entirely by the time this reads the record back.
    db_path.unlink()

    reconstructed = read_outcome(CHANNEL_ID, DAY, output_dir=outcomes_dir)

    assert reconstructed.schema_version == "1.0"
    assert reconstructed.channel_id == CHANNEL_ID
    assert reconstructed.channel_display_name == "Project Alpha"
    assert reconstructed.allowlisted is True
    assert reconstructed.roster == ["alice", "bob", "carol", "dave"]
    assert reconstructed.date.isoformat() == DAY.isoformat()

    assert [u.message_id for u in reconstructed.updates] == ["m-update"]
    assert reconstructed.updates[0].text == "Alice deployed the export job to staging."
    assert reconstructed.updates[0].quote == "Deployed the export job."
    assert [b.message_id for b in reconstructed.blockers] == ["m-blocker"]
    assert reconstructed.decisions == []
    assert reconstructed.questions == []


def test_reconstructed_participation_distinguishes_contributors_from_non_responders(tmp_path):
    """The record alone -- roster + participation, no db -- must be
    enough to answer "who contributed today" for every roster member."""
    db_path = tmp_path / "test.db"
    outcomes_dir = tmp_path / "outcomes"
    _seed_db(db_path)
    _seed_fact(db_path, message_id="m-update", author_id="alice", label="update", body="Shipped it.")
    # bob: no message at all -> no_message. carol: no message -> no_message.
    # dave: excluded (on leave).

    gateway = FakeGateway([_draft("m-update", "Alice shipped it.", quote="Shipped it.")])
    config = _config()
    result = generate_daily_summary(CHANNEL_ID, DAY, config, gateway, db_path=db_path)
    record = build_outcome_record(result, config)
    write_outcome(record, output_dir=outcomes_dir)
    db_path.unlink()

    reconstructed = read_outcome(CHANNEL_ID, DAY, output_dir=outcomes_dir)

    non_responders = {p.member_id: p.state for p in reconstructed.participation}
    assert non_responders == {"bob": "no_message", "carol": "no_message", "dave": "excluded"}
    contributors = set(reconstructed.roster) - set(non_responders)
    assert contributors == {"alice"}


def test_write_outcome_overwrites_a_previous_record_for_the_same_channel_and_day(tmp_path):
    db_path = tmp_path / "test.db"
    outcomes_dir = tmp_path / "outcomes"
    _seed_db(db_path)
    config = _config()

    first = build_outcome_record(
        generate_daily_summary(CHANNEL_ID, DAY, config, FakeGateway([]), db_path=db_path), config,
    )
    write_outcome(first, output_dir=outcomes_dir)

    _seed_fact(db_path, message_id="m-update", author_id="alice", label="update", body="Late update.")
    second = build_outcome_record(
        generate_daily_summary(
            CHANNEL_ID, DAY, config,
            FakeGateway([_draft("m-update", "Alice posted a late update.", quote="Late update.")]),
            db_path=db_path,
        ),
        config,
    )
    write_outcome(second, output_dir=outcomes_dir)

    reconstructed = read_outcome(CHANNEL_ID, DAY, output_dir=outcomes_dir)
    assert [u.message_id for u in reconstructed.updates] == ["m-update"]


def test_read_outcome_raises_for_a_record_that_was_never_written(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        read_outcome("nope", DAY, output_dir=tmp_path / "outcomes")


def test_channel_ids_with_special_characters_do_not_collide_or_escape_the_outcomes_dir(tmp_path):
    outcomes_dir = tmp_path / "outcomes"
    db_path = tmp_path / "test.db"
    _seed_db(db_path)
    config = _config()
    record = build_outcome_record(generate_daily_summary(CHANNEL_ID, DAY, config, FakeGateway([]), db_path=db_path), config)
    path = write_outcome(record, output_dir=outcomes_dir)

    assert outcomes_dir in path.parents
    # the slugged directory must not contain raw ':'/'@' -- those are exactly what _slug() replaces
    channel_dir = path.parent.name
    assert ":" not in channel_dir
    assert "@" not in channel_dir
