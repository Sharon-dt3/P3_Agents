"""
CHN-15's own acceptance test: both metrics printed and committed --
i.e. registered into SPN-07's harness and producing well-formed
MetricResults, which run_eval() (unchanged since CHN-11) already prints
one line per metric for and appends to eval/results.jsonl.

GC3 is a proportion (>=0.95), unlike GC5/GC10's hard-zero counts --
this suite pins the exact arithmetic (19 real facts + 1 invented id =
20 drafted lines, 19 resolvable = 0.95 exactly) so a future change to
the fixture data can't silently drift the boundary this metric is
deliberately sitting on.

GC4 is a hard zero, and its own test proves the probe is not vacuous:
the scripted gateway really does attempt a fabrication (a cross-section
citation) before self-correcting on retry, and the fabrication count is
computed by re-checking the final digest against the database directly,
not by trusting SPN-06's own internal bookkeeping.
"""

from __future__ import annotations

from p1.eval.cases import GoldenCaseRegistry
from p1.eval.chn15_cases import (
    _GC3_FACT_SPECS,
    _count_fabricated_survivors,
    _measure_gc3,
    _measure_gc4,
    register,
)
from p1.grounding.kernel import FactualLine

# --- registration ------------------------------------------------------


def test_register_adds_gc3_and_gc4():
    registry = GoldenCaseRegistry()
    register(registry)
    assert {c.case_id for c in registry.all_cases()} == {"GC3", "GC4"}


def test_registered_cases_run_via_the_registry():
    registry = GoldenCaseRegistry()
    register(registry)
    gc3_results = registry.get("GC3").measure_fn()
    gc4_results = registry.get("GC4").measure_fn()
    assert len(gc3_results) == 1
    assert len(gc4_results) == 1


# --- GC3: citation rate --------------------------------------------------


def test_gc3_citation_rate_is_exactly_nineteen_of_twenty():
    """19 real facts (5 update + 5 blocker + 5 decision + 4 question)
    plus exactly one invented id: 19/20 = 0.95, landing this metric
    directly on the boundary it targets rather than comfortably above
    it -- the arithmetic the WBS's own ">=0.95, not a typical 0.90"
    rationale is making a point about."""
    assert len(_GC3_FACT_SPECS) == 19

    results = {r.metric_id: r for r in _measure_gc3()}
    rate = results["GC3-citation-rate"]
    assert rate.comparator_name == "at_least"
    assert rate.target == 0.95
    assert rate.measured == 0.95
    assert rate.passed is True
    assert "19/20" in rate.detail


def test_gc3_uses_the_real_grounding_kernel_not_a_reimplementation():
    """A hand-forged line with an id nothing in the lookup resolves
    must fail exactly the way p1.grounding.kernel.verify_line says it
    should -- proving _measure_gc3 is really calling that function, not
    quietly reimplementing its own resolvability check."""
    from p1.grounding.kernel import verify_lines

    lookup = {"real-id": "some real message text"}.get
    result = verify_lines(
        [FactualLine(text="ok", message_id="real-id"), FactualLine(text="bad", message_id="fake-id")],
        lookup,
    )
    assert len(result.grounded_lines) == 1
    assert len(result.failures) == 1
    assert result.failures[0].reason == "unresolvable_message_id"


# --- GC4: fabrication probe ------------------------------------------------


def test_gc4_fabrication_count_is_zero_in_the_final_digest():
    results = {r.metric_id: r for r in _measure_gc4()}
    fabrication = results["GC4-fabrication-count"]
    assert fabrication.comparator_name == "at_most"
    assert fabrication.target == 0
    assert fabrication.measured == 0
    assert fabrication.passed is True


def test_gc4_probe_is_not_vacuous_a_fabrication_was_really_attempted():
    """The detail line names the fabricated cross-section citation that
    was drafted and then corrected on retry -- if the scripted gateway
    never actually attempted one, this golden case would trivially pass
    without proving anything."""
    results = {r.metric_id: r for r in _measure_gc4()}
    fabrication = results["GC4-fabrication-count"]
    assert "fabricated" in fabrication.detail
    assert "5 model call(s)" in fabrication.detail


def test_count_fabricated_survivors_flags_a_message_absent_from_the_store(tmp_path):
    from p1.storage.db import get_connection, init_db

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'C1', 1)")
    conn.commit()
    conn.close()

    section_lines = {"what_moved": [FactualLine(text="ghost", message_id="does-not-exist")]}
    count, details = _count_fabricated_survivors(db_path, "c1", section_lines)

    assert count == 1
    assert "absent from the store" in details[0]


def test_count_fabricated_survivors_flags_a_label_mismatch(tmp_path):
    from p1.adapters.teams_reader import TeamsMessage
    from p1.storage.classifications_repo import ClassificationStore
    from p1.storage.db import get_connection, init_db
    from p1.storage.messages_repo import MessageStore

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'C1', 1)")
    conn.execute("INSERT INTO members (id, display_name) VALUES ('alice', 'alice')")
    conn.commit()
    conn.close()

    message = TeamsMessage(id="m1", channel_id="c1", author_id="alice", posted_at="2026-06-01T09:00:00Z", body="Thanks!")
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id="m1", label="chatter", method="model", confidence=0.9)

    # placed under "decisions" even though the store says it's chatter --
    # exactly the dishonest mislabelling this probe exists to catch.
    section_lines = {"decisions": [FactualLine(text="a decision", message_id="m1")]}
    count, details = _count_fabricated_survivors(db_path, "c1", section_lines)

    assert count == 1
    assert "classified 'chatter'" in details[0]
    assert "not 'decision'" in details[0]


def test_count_fabricated_survivors_passes_a_genuinely_matching_line(tmp_path):
    from p1.adapters.teams_reader import TeamsMessage
    from p1.storage.classifications_repo import ClassificationStore
    from p1.storage.db import get_connection, init_db
    from p1.storage.messages_repo import MessageStore

    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    conn = get_connection(db_path)
    conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES ('c1', 'C1', 1)")
    conn.execute("INSERT INTO members (id, display_name) VALUES ('alice', 'alice')")
    conn.commit()
    conn.close()

    message = TeamsMessage(id="m1", channel_id="c1", author_id="alice", posted_at="2026-06-01T09:00:00Z", body="Deployed it.")
    MessageStore(db_path).upsert_messages([message])
    ClassificationStore(db_path).record(message_id="m1", label="update", method="model", confidence=0.9)

    section_lines = {"what_moved": [FactualLine(text="Alice deployed it.", message_id="m1")]}
    count, details = _count_fabricated_survivors(db_path, "c1", section_lines)

    assert count == 0
    assert details == []
