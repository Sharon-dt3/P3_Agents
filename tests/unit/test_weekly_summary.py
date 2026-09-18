"""
CHN-19's own acceptance test: "Every figure in the weekly roll-up
recomputes by hand from the stored message set." test_full_scenario_*
below seeds a four-member scenario (alice: participation/trend subject,
bob: recurring-blocker + trend subject, carol: excepted, dave:
decisions/questions subject) and hand-recomputes every participation
rate, trend delta, recurring blocker, decision and unanswered question
directly from the literal seed data below -- independently of
p1.reporting.weekly_facts's own logic, the same posture GC3/GC4/GC10
already take toward their own production code elsewhere in this repo.

Separately, test_narrative_* proves the one generated part of this
report -- the closing sentence -- can truly never carry a number
through to the persisted content, by scripting a gateway that
deliberately tries to smuggle a digit through on its first attempt.
"""

from __future__ import annotations

import json
from datetime import date, time

import pytest

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.llm.gateway import LLMResponse
from p1.reporting.weekly_facts import ExcludedMember
from p1.reporting.weekly_summary import (
    WeeklyNarrativeDraft,
    generate_and_persist_weekly_rollup,
    generate_weekly_rollup,
)
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore
from p1.storage.messages_repo import MessageStore

CHANNEL_ID = "wksum-channel"
TZ = "UTC"
WEEK_END = date(2026, 6, 5)  # Friday
ROSTER = ["alice", "bob", "carol", "dave"]


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID,
        "display_name": "Weekly Summary Channel",
        "allowlisted": True,
        "roster": ROSTER,
        "update_window_start": time(9, 0),
        "update_window_end": time(11, 0),
        "timezone": TZ,
        "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
        "non_working_dates": [],
        "length_floor": 10,
        "daily_digest_time": time(9, 0),
        "weekly_digest_day": "Fri",
        "weekly_digest_time": time(16, 0),
        "channel_owner_id": "alice",
        "exceptions": [{"member_id": "carol", "reason": "On leave"}],
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = get_connection(path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)", (CHANNEL_ID, "C"))
    for member_id in ROSTER:
        conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
    conn.commit()
    conn.close()
    return path


def _seed(db_path, message_id, author_id, day, label, *, body="text", thread_root_id=None):
    MessageStore(db_path).upsert_messages(
        [
            TeamsMessage(
                id=message_id, channel_id=CHANNEL_ID, author_id=author_id, thread_root_id=thread_root_id,
                posted_at=f"{day.isoformat()}T09:00:00+00:00", body=body,
                permalink=f"https://teams.microsoft.com/l/message/{CHANNEL_ID}/{message_id}",
            )
        ]
    )
    ClassificationStore(db_path).record(message_id=message_id, label=label, method="model", confidence=0.9)


class _ScriptedGateway:
    """Pops canned tool-call JSON in order -- the same FakeGateway shape
    test_daily_summary.py and the CHN-16/CHN-18 eval cases already use."""

    def __init__(self, texts: list[str]) -> None:
        self._texts = list(texts)
        self.calls = 0

    def generate(self, prompt: str, **kwargs) -> LLMResponse:
        self.calls += 1
        text = self._texts.pop(0)
        return LLMResponse(
            text=text, provider="anthropic", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def _narrative(text: str) -> str:
    return json.dumps({"narrative": text})


def _seed_full_scenario(db_path):
    """The scenario test_full_scenario_* hand-recomputes against below.
    Every number this test asserts is derived directly from these
    literal seed calls, not from re-reading weekly_facts.py's own code."""
    # alice: participation/trend subject only -- five plain updates,
    # never a blocker/decision/question, so her contributed-day count
    # is never affected by any other section's seeding.
    for day, msg_id in [
        (date(2026, 5, 25), "prior-alice-1"), (date(2026, 5, 26), "prior-alice-2"),
        (date(2026, 5, 27), "prior-alice-3"), (date(2026, 5, 28), "prior-alice-4"),
        (date(2026, 5, 29), "prior-alice-5"),
    ]:
        _seed(db_path, msg_id, "alice", day, "update")  # prior week: 5 of 5
    _seed(db_path, "cur-alice-1", "alice", date(2026, 6, 1), "update")
    _seed(db_path, "cur-alice-2", "alice", date(2026, 6, 2), "update")  # current week: 2 of 5

    # bob: recurring-blocker + trend subject. Prior week: one blocker,
    # one day only (not recurring). Current week: blockers on two
    # distinct days (recurring).
    _seed(db_path, "prior-bob-1", "bob", date(2026, 5, 25), "blocker")  # prior week: 1 of 5
    _seed(db_path, "cur-bob-blk-1", "bob", date(2026, 6, 1), "blocker", body="Blocked on the staging box.")
    _seed(db_path, "cur-bob-blk-2", "bob", date(2026, 6, 3), "blocker", body="Still blocked on the staging box.")
    # current week: 2 of 5 (Mon, Wed)

    # carol: excepted (on leave) -- posts nothing.

    # dave: decisions/questions subject. No prior-week activity at all
    # (prior rate exactly 0.0, not None -- there ARE working days, he
    # just didn't post).
    _seed(db_path, "dave-dec-1", "dave", date(2026, 6, 4), "decision", body="We decided to launch Friday.")
    _seed(db_path, "dave-q1", "dave", date(2026, 6, 1), "question", body="Who owns the staging box?")
    _seed(db_path, "dave-q1-reply", "alice", date(2026, 6, 2), "chatter", thread_root_id="dave-q1")
    _seed(db_path, "dave-q2", "dave", date(2026, 6, 4), "question", body="Are we still shipping Friday?")
    _seed(db_path, "dave-q3", "dave", date(2026, 6, 5), "question", body="Who is on call this weekend?")
    _seed(db_path, "dave-q3-reply", "bob", date(2026, 6, 8), "chatter", thread_root_id="dave-q3")
    # dave current-week contributing days: Mon (q1), Thu (decision + q2, same day), Fri (q3) = 3 of 5


# --- CHN-19's own acceptance test: every figure recomputes by hand ---------


def test_full_scenario_every_figure_recomputes_by_hand(db_path):
    _seed_full_scenario(db_path)
    gateway = _ScriptedGateway([_narrative("The team kept steady momentum through most of the week.")])

    result = generate_weekly_rollup(CHANNEL_ID, WEEK_END, _config(), gateway, db_path=db_path)
    facts = result.facts

    # -- participation & trend: hand-computed straight from the seed
    # calls above, not from weekly_facts.py's own arithmetic.
    alice = facts.participation["alice"]
    assert (alice.current.contributed_days, alice.current.working_days) == (2, 5)
    assert alice.current.rate == pytest.approx(2 / 5)
    assert (alice.prior.contributed_days, alice.prior.working_days) == (5, 5)
    assert alice.prior.rate == pytest.approx(5 / 5)
    assert alice.delta == pytest.approx(2 / 5 - 5 / 5)

    bob = facts.participation["bob"]
    assert (bob.current.contributed_days, bob.current.working_days) == (2, 5)
    assert (bob.prior.contributed_days, bob.prior.working_days) == (1, 5)
    assert bob.delta == pytest.approx(2 / 5 - 1 / 5)

    dave = facts.participation["dave"]
    assert (dave.current.contributed_days, dave.current.working_days) == (3, 5)
    assert dave.prior.rate == pytest.approx(0.0)
    assert dave.delta == pytest.approx(3 / 5 - 0.0)

    # carol is excepted, not a rate of zero.
    assert "carol" not in facts.participation
    assert facts.excluded_members == (ExcludedMember(member_id="carol", reason="On leave"),)

    # -- recurring blockers: bob only, current week only, in
    # chronological order -- the prior week's single blocker never
    # appears here at all.
    assert len(facts.recurring_blockers) == 1
    blocker = facts.recurring_blockers[0]
    assert blocker.author_id == "bob"
    assert blocker.message_ids == ("cur-bob-blk-1", "cur-bob-blk-2")
    assert blocker.days == ("2026-06-01", "2026-06-03")

    # -- decisions: exactly dave's one decision this week.
    assert [f.message_id for f in facts.decisions] == ["dave-dec-1"]
    assert facts.decisions[0].body_raw == "We decided to launch Friday."

    # -- unanswered all week: q1 was answered inside the week (excluded);
    # q2 never got a reply; q3's reply arrived the following week, so it
    # still counts as unanswered ALL WEEK even though it was eventually
    # answered.
    assert [f.message_id for f in facts.unanswered_questions] == ["dave-q2", "dave-q3"]

    # -- the rendered content actually contains these same figures,
    # verbatim, not just the in-memory facts object.
    assert "**alice**: 40%" in result.content
    assert "**bob**: 40%" in result.content
    assert "**dave**: 60%" in result.content
    assert "**carol**: excluded (On leave)" in result.content
    assert '"Blocked on the staging box."' in result.content
    assert '"Still blocked on the staging box."' in result.content
    assert '"We decided to launch Friday."' in result.content
    assert '"Are we still shipping Friday?"' in result.content
    assert '"Who is on call this weekend?"' in result.content
    assert '"Who owns the staging box?"' not in result.content  # answered within week -- must not appear


def test_a_channel_with_zero_traffic_produces_an_honest_empty_rollup(db_path):
    gateway = _ScriptedGateway([_narrative("Nobody posted anything of note this week.")])
    result = generate_weekly_rollup(CHANNEL_ID, WEEK_END, _config(), gateway, db_path=db_path)
    assert all(p.current.rate == 0.0 for p in result.facts.participation.values())
    assert result.facts.recurring_blockers == []
    assert result.facts.decisions == []
    assert result.facts.unanswered_questions == []
    assert "No recurring blockers this week." in result.content
    assert "No decisions were taken this week." in result.content
    assert "No questions went unanswered all week." in result.content


# --- the narrative sentence: enforced, not merely requested, to carry no digit --


def test_narrative_with_a_digit_is_rejected_and_retried(db_path):
    gateway = _ScriptedGateway([
        _narrative("Participation held at 40% this week."),  # rejected: contains digits
        _narrative("Participation held roughly steady this week."),  # accepted
    ])
    result = generate_weekly_rollup(CHANNEL_ID, WEEK_END, _config(), gateway, db_path=db_path)
    assert gateway.calls == 2
    assert result.narrative == "Participation held roughly steady this week."
    assert not any(char.isdigit() for char in result.content.split("## This week in brief")[1])


def test_weekly_narrative_draft_validator_rejects_any_digit():
    with pytest.raises(ValueError, match="never contain a digit"):
        WeeklyNarrativeDraft(narrative="We closed 3 decisions this week.")


def test_weekly_narrative_draft_validator_accepts_digit_free_text():
    draft = WeeklyNarrativeDraft(narrative="The team wrapped up a couple of open items.")
    assert draft.narrative == "The team wrapped up a couple of open items."


# --- persistence / idempotency -------------------------------------------


def test_generate_and_persist_upserts_by_idempotency_key(db_path):
    gateway = _ScriptedGateway([
        _narrative("First pass narrative."), _narrative("Second pass narrative."),
    ])
    generate_and_persist_weekly_rollup(CHANNEL_ID, WEEK_END, _config(), gateway, db_path=db_path)
    generate_and_persist_weekly_rollup(CHANNEL_ID, WEEK_END, _config(), gateway, db_path=db_path)

    row = DigestStore(db_path).get_by_idempotency_key(f"{CHANNEL_ID}:2026-06-05:weekly")
    assert row is not None
    assert row["type"] == "weekly"
    assert "Second pass narrative." in row["content"]

    conn = get_connection(db_path)
    try:
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM digests WHERE channel_id = ? AND type = 'weekly'", (CHANNEL_ID,)
        ).fetchone()["n"]
    finally:
        conn.close()
    assert count == 1
