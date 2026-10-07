"""P1 now writes the channel's outcome record after each daily digest (opt-in), so P2 has something to read.

CHN-26 built the outcome record (the contract P2 consumes: one JSON file per channel per day) but nothing in P1's
running jobs ever wrote one, so P2's commitment tracking had no live input. This hooks the writer into the daily digest job,
and is built so it changes nothing else about how P1 works:

- OFF unless P1_WRITE_OUTCOME_RECORDS=1: with it unset, no file is written and nothing differs;
- it only writes a file from content the digest already built: no model call, no Teams call, nothing posted or approved;
- the digest, the proposal and the model calls are identical with it on and off;
- it never fails the job: if the file cannot be written the digest still goes ahead and the failure is only logged;
- it is not gated on the digest's own approval (CHN-26's decision): a digest awaiting approval still gets its record.
"""

from __future__ import annotations

import json
import logging
from datetime import date, time
from pathlib import Path

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.approval.proposals import ProposalStore
from p1.config.schema import ChannelConfig
from p1.contracts.outcome_record import read_outcome
from p1.llm.gateway import LLMResponse
from p1.publishing.daily_job import (
    AWAITING_APPROVAL,
    SKIPPED_NON_WORKING_DAY,
    run_daily_digest_job,
)
from p1.publishing.outcome_emission import (
    ENV_DIR,
    ENV_ENABLED,
    emit_outcome_record,
    outcomes_dir,
)
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore
from p1.storage.messages_repo import MessageStore

CHANNEL = "19:job-channel@thread.tacv2"
MONDAY, SATURDAY = date(2026, 6, 1), date(2026, 6, 6)
PROMISE = "I'll have the export fix done by 2026-06-05."


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL, "display_name": "Job Channel", "allowlisted": True, "roster": ["alice", "bob"],
        "update_window_start": time(9, 0), "update_window_end": time(11, 0), "timezone": "UTC",
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"], "daily_digest_time": time(9, 0), "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0), "channel_owner_id": "alice",
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


class _Gateway:
    """Writes the one update line the day's one update message supports."""

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        text = json.dumps({"lines": [{"message_id": "m-1", "text": PROMISE, "quote": PROMISE}]})
        return LLMResponse(text=text, provider="fake", model="fake", prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False)


class _Publisher:
    def __init__(self):
        self.calls = []

    def post_channel_message(self, channel_id, content):
        self.calls.append((channel_id, content))
        return {"ok": True}


def _database(path) -> str:
    init_db(str(path))
    conn = get_connection(str(path))
    try:
        conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'Job Channel', 1)", (CHANNEL,))
        for member in ("alice", "bob"):
            conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member, member))
        conn.commit()
    finally:
        conn.close()
    MessageStore(str(path)).upsert_messages([TeamsMessage(id="m-1", channel_id=CHANNEL, author_id="alice",
                                                          posted_at=f"{MONDAY.isoformat()}T09:30:00+00:00", body=PROMISE,
                                                          permalink="https://t/m-1")])
    ClassificationStore(str(path)).record(message_id="m-1", label="update", method="model", confidence=0.9)
    return str(path)


@pytest.fixture()
def world(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_ENABLED, raising=False)
    monkeypatch.setenv(ENV_DIR, str(tmp_path / "outcomes"))
    return {"db": _database(tmp_path / "p1.db"), "dir": tmp_path / "outcomes", "tmp": tmp_path}


def _run(world, day=MONDAY, gateway=None, publisher=None, db=None):
    return run_daily_digest_job(CHANNEL, _config(), gateway or _Gateway(), publisher or _Publisher(), day=day, db_path=db or world["db"])


# --- off by default --------------------------------------------------------------------------------------------------------------------


def test_nothing_is_written_unless_it_is_switched_on(world):
    _run(world)

    assert not world["dir"].exists()  # not even the folder


@pytest.mark.parametrize("value", ["", "0", "true", "yes"])
def test_only_exactly_one_switches_it_on(world, monkeypatch, value):
    monkeypatch.setenv(ENV_ENABLED, value)

    _run(world)

    assert not world["dir"].exists()


# --- what is written ------------------------------------------------------------------------------------------------------------------------


def test_switched_on_the_daily_job_writes_the_days_outcome_record(world, monkeypatch):
    monkeypatch.setenv(ENV_ENABLED, "1")

    _run(world)

    record = read_outcome(CHANNEL, MONDAY, output_dir=world["dir"])
    assert record.channel_id == CHANNEL and record.date == MONDAY and record.allowlisted is True and record.schema_version == "1.0"
    assert [(u.message_id, u.text) for u in record.updates] == [("m-1", PROMISE)] and record.updates[0].quote == PROMISE
    assert record.roster == ["alice", "bob"]
    assert [(p.member_id, p.state) for p in record.participation] == [("bob", "no_message")]  # alice posted, bob did not


def test_the_file_is_one_per_channel_per_day_where_p2_looks_for_it(world, monkeypatch):
    monkeypatch.setenv(ENV_ENABLED, "1")

    _run(world)

    files = sorted(p.relative_to(world["dir"]) for p in world["dir"].rglob("*.json"))
    assert files == [Path("19_job-channel_thread.tacv2") / "2026-06-01.json"]


def test_the_record_holds_exactly_the_evidence_the_digest_cites(world, monkeypatch):
    monkeypatch.setenv(ENV_ENABLED, "1")

    _run(world)

    proposal = ProposalStore(world["db"]).get_by_idempotency_key(f"{CHANNEL}:{MONDAY.isoformat()}:daily_publish")
    record = read_outcome(CHANNEL, MONDAY, output_dir=world["dir"])
    assert set(proposal.source_refs) == {item.message_id for item in [*record.updates, *record.blockers, *record.decisions, *record.questions]}


def test_running_the_job_again_rewrites_the_same_days_file_not_a_second_one(world, monkeypatch):
    monkeypatch.setenv(ENV_ENABLED, "1")
    _run(world)

    _run(world)

    assert len(list(world["dir"].rglob("*.json"))) == 1


def test_a_digest_still_waiting_for_its_first_approval_still_gets_its_record(world, monkeypatch):
    """CHN-26's decision: the record is about what happened in the channel, not about whether the Teams post was approved."""
    monkeypatch.setenv(ENV_ENABLED, "1")

    result = _run(world)

    assert result.status == AWAITING_APPROVAL and read_outcome(CHANNEL, MONDAY, output_dir=world["dir"]).updates


def test_a_non_working_day_writes_nothing(world, monkeypatch):
    monkeypatch.setenv(ENV_ENABLED, "1")

    result = _run(world, day=SATURDAY)

    assert result.status == SKIPPED_NON_WORKING_DAY and not world["dir"].exists()


# --- it changes nothing else about how P1 works --------------------------------------------------------------------------------------------


def _fingerprint(db, gateway, publisher, result):
    store = ProposalStore(db)
    proposal = store.get_by_idempotency_key(f"{CHANNEL}:{MONDAY.isoformat()}:daily_publish")
    digest = DigestStore(db).get_by_idempotency_key(f"{CHANNEL}:{MONDAY.isoformat()}:daily")
    return {"status": result.status, "detail": result.detail, "model_calls": gateway.calls, "posts": publisher.calls,
            "proposal_status": proposal.status, "proposal_payload": proposal.payload, "source_refs": proposal.source_refs,
            "digest": digest["content"] if isinstance(digest, dict) else digest.content}


def test_the_digest_the_proposal_and_the_model_calls_are_identical_with_it_on_and_off(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_DIR, str(tmp_path / "outcomes"))
    outcomes = {}
    for label, switch in (("off", None), ("on", "1")):
        if switch:
            monkeypatch.setenv(ENV_ENABLED, switch)
        else:
            monkeypatch.delenv(ENV_ENABLED, raising=False)
        db, gateway, publisher = _database(tmp_path / f"{label}.db"), _Gateway(), _Publisher()
        result = run_daily_digest_job(CHANNEL, _config(), gateway, publisher, day=MONDAY, db_path=db)
        outcomes[label] = _fingerprint(db, gateway, publisher, result)

    assert outcomes["on"] == outcomes["off"]
    assert outcomes["on"]["model_calls"] == 1  # the one section the day has: writing the record added no model call


# --- it can never fail the job ---------------------------------------------------------------------------------------------------------------


def test_if_the_file_cannot_be_written_the_digest_still_goes_ahead(world, monkeypatch, caplog):
    blocker = world["tmp"] / "not-a-folder"
    blocker.write_text("a file where the outcomes folder should be")
    monkeypatch.setenv(ENV_ENABLED, "1")
    monkeypatch.setenv(ENV_DIR, str(blocker))

    with caplog.at_level(logging.WARNING):
        result = _run(world)

    assert result.status == AWAITING_APPROVAL  # the job did what it always does
    assert ProposalStore(world["db"]).get_by_idempotency_key(f"{CHANNEL}:{MONDAY.isoformat()}:daily_publish") is not None
    assert any("outcome record" in r.message for r in caplog.records)


def test_the_writer_itself_never_raises(world, monkeypatch):
    import p1.publishing.outcome_emission as emission

    monkeypatch.setenv(ENV_ENABLED, "1")
    monkeypatch.setattr(emission, "build_outcome_record", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    assert emit_outcome_record(object(), _config()) is None  # logged, not raised


# --- where it goes ----------------------------------------------------------------------------------------------------------------------------


def test_the_folder_defaults_to_outcomes_in_the_p1_repo_where_p2_looks(monkeypatch):
    monkeypatch.delenv(ENV_DIR, raising=False)

    folder = outcomes_dir()

    assert folder.name == "outcomes" and folder.is_absolute() and (folder.parent / "src" / "p1").is_dir()


def test_the_folder_can_be_set(monkeypatch, tmp_path):
    monkeypatch.setenv(ENV_DIR, str(tmp_path / "elsewhere"))

    assert outcomes_dir() == tmp_path / "elsewhere"
