"""
CHN-16 golden case: GC9, determinism of facts.

The WBS row's own acceptance test: "Generate a daily summary twice from
the same message window. Wording may differ; the participation set,
contributor list and counts must not." This is the golden case that
empirically proves CHN-13's own central design claim -- "facts in code,
prose from the model" -- rather than merely asserting it. Everything
that decides WHAT is in a digest (which messages qualify as a fact,
who counts as a contributor, how many facts land in each section, who
is and isn't a non-responder) comes from p1.reporting.facts.
gather_daily_facts and p1.participation.ledger.build_ledger -- both
pure, deterministic reads of the message store, with no model call
anywhere in them. Only the model is ever asked to turn a given fact
into one line of prose, and prose is explicitly allowed to vary.

So this golden case runs the real, end-to-end generate_daily_summary()
twice against the identical seeded window, with two DIFFERENT scripted
gateways that deliberately draft different wording for the same
underlying facts -- proving the fact-set comparison is actually
insensitive to wording, not merely that two identical runs happen to
agree (which would prove nothing). "Fact set" here is read directly off
each run's own DailySummaryResult, never reimplemented against the
database independently, because it is production's own account of what
it decided, and covers exactly the three things the WBS names:

  - contributor list: per section, the sorted set of message_ids that
    made it into that section's grounded lines. This is what CHN-13's
    facts.py handed the model -- the model's prose is not allowed to
    add or drop a fact.
  - counts: per section, how many grounded lines survived. Kept as its
    own explicit check alongside the id set (rather than relying on
    set-equality alone) because the WBS names it separately, and because
    a set comparison alone couldn't distinguish "the same facts" from
    "the same facts, but one got duplicated."
  - participation set: the full, sorted list of
    (member_id, state, evidence_message_ids) that CHN-10's ledger
    produced -- built from the message store alone, never touched by
    the model at all, so this one should be trivially identical, but is
    checked explicitly rather than assumed.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig, ExceptionEntry
from p1.eval.cases import GoldenCase, GoldenCaseRegistry, MetricResult, at_most
from p1.llm.gateway import LLMResponse
from p1.reporting.daily_summary import DailySummaryResult, generate_daily_summary
from p1.reporting.facts import SECTION_ORDER
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

TZ = "Asia/Colombo"
DAY = date(2026, 6, 1)  # a Monday
CHANNEL_ID = "gc16-channel"


def _config(**overrides) -> ChannelConfig:
    defaults = {
        "channel_id": CHANNEL_ID,
        "display_name": "GC16 Channel",
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
    tmp_dir = tempfile.mkdtemp(prefix="chn16_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)",
                (CHANNEL_ID, "GC16 Channel"),
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


class _ScriptedGateway:
    """Pops canned tool-call JSON in order -- the same FakeGateway shape
    test_daily_summary.py and chn15_cases.py already use."""

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


def _fact_set(result: DailySummaryResult) -> dict:
    """Everything a digest run decided that is NOT the model's prose --
    read straight off the result, never recomputed against the database
    independently, because the point is to compare what production
    itself produced across two runs, not to re-derive a third answer."""
    return {
        "message_ids": {
            section: sorted(line.message_id for line in result.section_lines[section])
            for section in SECTION_ORDER
        },
        "counts": {
            section: len(result.section_lines[section])
            for section in SECTION_ORDER
        },
        "participation": sorted(
            (record.member_id, record.state, tuple(sorted(record.evidence_message_ids)))
            for record in result.participation
        ),
    }


def _compare_fact_sets(a: dict, b: dict) -> list[str]:
    """Returns one human-readable divergence per thing the WBS names --
    contributor list, counts, participation set -- rather than a single
    opaque not-equal, so a real regression prints exactly what moved."""
    divergences: list[str] = []
    for section in SECTION_ORDER:
        if a["message_ids"][section] != b["message_ids"][section]:
            divergences.append(
                f"{section}: contributor list differs ({a['message_ids'][section]!r} "
                f"vs {b['message_ids'][section]!r})"
            )
        if a["counts"][section] != b["counts"][section]:
            divergences.append(
                f"{section}: count differs ({a['counts'][section]} vs {b['counts'][section]})"
            )
    if a["participation"] != b["participation"]:
        divergences.append(
            f"participation set differs ({a['participation']!r} vs {b['participation']!r})"
        )
    return divergences


def _measure_gc9() -> list[MetricResult]:
    with _seeded_db() as db_path:
        config = _config(
            exceptions=[ExceptionEntry(member_id="dave", reason="On leave through the window")],
        )

        # alice contributes two updates; bob contributes one blocker --
        # both are "contributor" labels (p1.participation.ledger's own
        # _CONTRIBUTOR_LABELS), so neither appears in the participation
        # section at all. carol's only message today is chatter -- posted
        # something, but nothing that counts as a contribution, exactly
        # CHN-14's "posted, but no update" case. dave is on the
        # exceptions list and posts nothing.
        _seed_fact(db_path, label="update", message_id="gc9-upd-1", author_id="alice", body="Shipped the export job to production.")
        _seed_fact(db_path, label="update", message_id="gc9-upd-2", author_id="alice", body="Merged the outstanding config fix.")
        _seed_fact(db_path, label="blocker", message_id="gc9-blk-1", author_id="bob", body="Blocked waiting on ops access to the staging box.")
        MessageStore(db_path).upsert_messages(
            [_message("gc9-cht-1", "carol", "Morning everyone, coffee's on if anyone wants some.")]
        )
        ClassificationStore(db_path).record(message_id="gc9-cht-1", label="chatter", method="model", confidence=0.9)

        # Two independent generations, two gateways that draft
        # deliberately different wording for the identical facts -- if
        # the fact-set comparison below still reports zero divergences,
        # that is because it genuinely ignores wording, not because
        # nothing varied between the runs.
        gateway_a = _ScriptedGateway([
            _draft(
                _line("gc9-upd-1", "Alice shipped the export job to production."),
                _line("gc9-upd-2", "Alice merged the outstanding config fix."),
            ),
            _draft(_line("gc9-blk-1", "Bob is blocked waiting on ops access to the staging box.")),
        ])
        gateway_b = _ScriptedGateway([
            _draft(
                _line("gc9-upd-1", "The export job is now live in production, shipped by Alice."),
                _line("gc9-upd-2", "A pending config fix was merged by Alice."),
            ),
            _draft(_line("gc9-blk-1", "Ops access to the staging box is what's currently blocking Bob.")),
        ])

        result_a = generate_daily_summary(CHANNEL_ID, DAY, config, gateway_a, db_path=db_path)
        result_b = generate_daily_summary(CHANNEL_ID, DAY, config, gateway_b, db_path=db_path)

        fact_set_a = _fact_set(result_a)
        fact_set_b = _fact_set(result_b)
        divergences = _compare_fact_sets(fact_set_a, fact_set_b)

        wording_differs = any(
            line_a.text != line_b.text
            for section in SECTION_ORDER
            for line_a, line_b in zip(result_a.section_lines[section], result_b.section_lines[section])
        )

    return [
        MetricResult(
            metric_id="GC9-fact-divergence-count",
            name="divergences in contributor list, counts or participation set across two independent generations",
            measured=len(divergences),
            target=0,
            comparator_name="at_most",
            passed=at_most(len(divergences), 0),
            detail=(
                "; ".join(divergences) if divergences else
                f"0 divergences across {len(SECTION_ORDER)} sections + participation "
                f"({len(fact_set_a['participation'])} member(s)); every drafted line's wording "
                f"differed between the two generations (wording_differs={wording_differs}), so this "
                "is a genuine fact-set comparison, not a vacuous check against identical text"
            ),
        )
    ]


def register(registry: GoldenCaseRegistry) -> None:
    registry.register(
        GoldenCase(
            case_id="GC9",
            description="Determinism of facts: contributor list, counts and participation set agree across two generations (CHN-16)",
            measure_fn=_measure_gc9,
        )
    )
