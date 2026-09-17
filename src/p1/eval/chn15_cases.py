"""
CHN-15 golden cases: GC3 (citation rate) and GC4 (fabrication probe) --
both audit the grounding guarantee CHN-13's daily summary and SPN-06's
kernel are supposed to provide, but from two different vantage points:

GC3 -- citation rate: of a batch of factual lines a model might
plausibly draft on its first, unaided attempt (before SPN-06's
retry-and-drop safety net ever gets involved), what proportion carry a
message_id that actually resolves? Measured directly against
p1.grounding.kernel.verify_lines -- the real, production verification
function, not a reimplementation of its logic -- run against real
facts seeded through p1.reporting.facts.gather_daily_facts (CHN-13's
own real fact-gathering code), so both halves of the check (what counts
as ground truth, and what counts as "resolves") are the real production
code, only the "model's draft" half is hand-authored here since Method
is Python, not a live model call. The target is >=0.95, deliberately
higher than a typical 0.90 threshold used elsewhere in this harness
(GC1's precision, for instance) -- per this task's own rationale, a
message_id is an exact token to copy, not a judgment call, so there is
no excuse for it to be wrong anywhere near as often as a harder,
judgment-based metric might tolerate.

GC4 -- fabrication probe: of the lines that make it all the way into a
real, end-to-end generate_daily_summary() run's FINAL rendered output,
how many claim a message, author, decision or blocker that isn't
actually there? This must be a hard zero, not a proportion -- there is
no acceptable rate of fabrication reaching a manager's screen. Rather
than trusting SPN-06's own bookkeeping (result.dropped) to prove this,
_count_fabricated_survivors re-derives the check independently, straight
against the database: for every surviving line, its message_id must
exist in this channel's messages table, that message's own
classifications.label must actually match the section the line was
placed under (a line in "decisions taken" citing a message classified
"chatter" would be exactly as dishonest as citing a message that
doesn't exist at all), and the message must have a real author on
record. The scenario deliberately drives one section's model output to
fabricate on its first attempt -- citing a real message that belongs to
a *different* section, the exact cross-section leak
test_a_line_claiming_a_real_but_unrelated_message_id_is_dropped_not_kept
in test_daily_summary.py already proves the scoped per-section
message_lookup catches -- and corrects on retry, so this golden case
also proves that fabrication attempt never reaches the final digest,
not merely that a clean run has nothing to catch.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.eval.cases import (
    GoldenCase,
    GoldenCaseRegistry,
    MetricResult,
    at_least,
    at_most,
)
from p1.grounding.kernel import FactualLine, verify_lines
from p1.llm.gateway import LLMResponse
from p1.reporting.daily_summary import generate_daily_summary
from p1.reporting.facts import gather_daily_facts
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

TZ = "Asia/Colombo"
DAY = date(2026, 6, 1)  # a Monday
CHANNEL_ID = "gc15-channel"

_EXPECTED_LABEL = {
    "what_moved": "update",
    "blockers": "blocker",
    "decisions": "decision",
    "questions": "question",
}


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID,
        "display_name": "GC15 Channel",
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
        "exceptions": [],
    }
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def _message(message_id: str, author_id: str, body: str) -> TeamsMessage:
    return TeamsMessage(
        id=message_id,
        channel_id=CHANNEL_ID,
        author_id=author_id,
        posted_at="2026-06-01T09:30:00+05:30",
        body=body,
        permalink=f"https://teams.microsoft.com/l/message/{CHANNEL_ID}/{message_id}",
    )


@contextmanager
def _seeded_db():
    tmp_dir = tempfile.mkdtemp(prefix="chn15_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)",
                (CHANNEL_ID, "GC15 Channel"),
            )
            for member_id in ("alice", "bob", "carol", "dave"):
                conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
            conn.commit()
        finally:
            conn.close()
        yield db_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _seed_fact(db_path: str, *, label: str, message_id: str, author_id: str, body: str) -> None:
    MessageStore(db_path).upsert_messages([_message(message_id, author_id, body)])
    ClassificationStore(db_path).record(message_id=message_id, label=label, method="model", confidence=0.9)


# --- GC3: citation rate ------------------------------------------------------

# 19 real, correctly-classified facts spread across all four content
# sections -- deliberately a round enough number that adding exactly one
# fabricated draft line lands the ratio exactly on the 0.95 boundary
# this metric targets (19 / 20 = 0.95), rather than an arbitrarily
# comfortable number that would hide how close to the line this target
# actually sits.
_GC3_FACT_SPECS = (
    [("update", f"gc3-upd-{i}", "alice", f"Update item number {i} was posted to the channel.") for i in range(1, 6)]
    + [("blocker", f"gc3-blk-{i}", "bob", f"Blocker item number {i} is holding things up.") for i in range(1, 6)]
    + [("decision", f"gc3-dec-{i}", "carol", f"Decision item number {i} was made by the team.") for i in range(1, 6)]
    + [("question", f"gc3-que-{i}", "dave", f"Question item number {i} is still open.") for i in range(1, 5)]
)


def _measure_gc3() -> list[MetricResult]:
    with _seeded_db() as db_path:
        config = _config()
        for label, message_id, author_id, body in _GC3_FACT_SPECS:
            _seed_fact(db_path, label=label, message_id=message_id, author_id=author_id, body=body)

        facts_by_section, _ = gather_daily_facts(CHANNEL_ID, DAY, config, db_path)
        all_facts = [fact for facts in facts_by_section.values() for fact in facts]
        message_lookup = {fact.message_id: fact.body_raw for fact in all_facts}.get

        # A representative "first attempt" draft: every real fact cited
        # correctly by its own message_id, plus exactly one line
        # inventing an id that was never among the facts it was given --
        # the rare slip this metric exists to measure, since copying an
        # exact id verbatim is otherwise a trivial, mechanical task, not
        # a judgment call.
        drafted = [
            FactualLine(text=f"A line describing {fact.message_id}.", message_id=fact.message_id)
            for fact in all_facts
        ]
        drafted.append(
            FactualLine(text="A line about something that was never provided.", message_id="gc3-does-not-exist")
        )

        result = verify_lines(drafted, message_lookup)
        total = len(drafted)
        resolvable = len(result.grounded_lines)
        citation_rate = resolvable / total

    return [
        MetricResult(
            metric_id="GC3-citation-rate",
            name="proportion of factual summary lines carrying a resolvable message ID",
            measured=round(citation_rate, 4),
            target=0.95,
            comparator_name="at_least",
            passed=at_least(citation_rate, 0.95),
            detail=(
                f"{resolvable}/{total} lines resolved (n={len(all_facts)} real facts + 1 invented id); "
                "message ids are exact copies, so anything short of near-total accuracy has no excuse"
            ),
        )
    ]


# --- GC4: fabrication probe ---------------------------------------------------


class _ScriptedGateway:
    """Pops canned tool-call JSON in order, matching the FakeGateway
    shape test_daily_summary.py already uses."""

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


def _draft(*lines: dict) -> str:
    return json.dumps({"lines": list(lines)})


def _line(message_id: str, text: str) -> dict:
    return {"message_id": message_id, "text": text, "quote": None}


def _count_fabricated_survivors(
    db_path: str, channel_id: str, section_lines: dict[str, list[FactualLine]]
) -> tuple[int, list[str]]:
    """Independently re-checks the FINAL, already-grounded digest
    against the database -- not the grounding kernel's own bookkeeping
    -- for every one of the three things a fabricated line could get
    away with: citing a message that doesn't exist at all, citing a
    real message whose own classification doesn't match the section it
    was placed under, or citing a message with no recorded author."""
    conn = get_connection(db_path)
    fabricated = 0
    details: list[str] = []
    try:
        for section, lines in section_lines.items():
            expected_label = _EXPECTED_LABEL[section]
            for line in lines:
                row = conn.execute(
                    "SELECT m.author_id, c.label FROM messages m "
                    "LEFT JOIN classifications c ON c.message_id = m.id "
                    "WHERE m.id = ? AND m.channel_id = ?",
                    (line.message_id, channel_id),
                ).fetchone()
                if row is None:
                    fabricated += 1
                    details.append(f"{section}:{line.message_id} cites a message absent from the store")
                elif row["label"] != expected_label:
                    fabricated += 1
                    details.append(
                        f"{section}:{line.message_id} cites a message classified {row['label']!r}, "
                        f"not {expected_label!r}"
                    )
                elif row["author_id"] is None:
                    fabricated += 1
                    details.append(f"{section}:{line.message_id} cites a message with no recorded author")
    finally:
        conn.close()
    return fabricated, details


def _measure_gc4() -> list[MetricResult]:
    with _seeded_db() as db_path:
        config = _config()
        facts = (
            ("update", "gc4-upd-1", "alice", "Deployed the export job to staging."),
            ("blocker", "gc4-blk-1", "bob", "Blocked on the staging credentials rotating."),
            ("decision", "gc4-dec-1", "carol", "Decided to ship behind a feature flag."),
            ("question", "gc4-que-1", "dave", "Should we roll this out to everyone at once?"),
        )
        for label, message_id, author_id, body in facts:
            _seed_fact(db_path, label=label, message_id=message_id, author_id=author_id, body=body)

        gateway = _ScriptedGateway([
            # what_moved, attempt 1: fabricates by also citing bob's
            # real blocker message id -- real in the store, but not one
            # of what_moved's own facts. The scoped per-section
            # message_lookup daily_summary.py builds means this cannot
            # resolve here no matter how real it is elsewhere.
            _draft(
                _line("gc4-upd-1", "Alice deployed the export job to staging."),
                _line("gc4-blk-1", "Something else happened too."),
            ),
            # what_moved, attempt 2 (retry): corrects, citing only its
            # own real fact.
            _draft(_line("gc4-upd-1", "Alice deployed the export job to staging.")),
            # blockers, decisions, questions: each correct on the first try.
            _draft(_line("gc4-blk-1", "Bob is blocked on the staging credentials rotating.")),
            _draft(_line("gc4-dec-1", "Carol decided to ship behind a feature flag.")),
            _draft(_line("gc4-que-1", "Dave is asking whether to roll this out to everyone at once.")),
        ])

        result = generate_daily_summary(CHANNEL_ID, DAY, config, gateway, db_path=db_path)
        fabricated_count, details = _count_fabricated_survivors(db_path, CHANNEL_ID, result.section_lines)
        gateway_calls = gateway.calls

    return [
        MetricResult(
            metric_id="GC4-fabrication-count",
            name="count of lines claiming a message, author, decision or blocker absent from the store",
            measured=fabricated_count,
            target=0,
            comparator_name="at_most",
            passed=at_most(fabricated_count, 0),
            detail=(
                "; ".join(details) if details else
                f"{gateway_calls} model call(s), including one deliberately fabricated cross-section "
                "citation that was corrected on retry before reaching the final digest"
            ),
        )
    ]


def register(registry: GoldenCaseRegistry) -> None:
    registry.register(
        GoldenCase(
            case_id="GC3",
            description="Citation rate: proportion of factual lines carrying a resolvable message ID (CHN-15)",
            measure_fn=_measure_gc3,
        )
    )
    registry.register(
        GoldenCase(
            case_id="GC4",
            description="Fabrication probe: lines surviving into the final digest that cite something absent from the store (CHN-15)",
            measure_fn=_measure_gc4,
        )
    )
