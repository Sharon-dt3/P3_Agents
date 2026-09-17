"""
CHN-16's own acceptance test: "Fact-set comparison across two
generations prints zero divergences." This suite proves three things
about that comparison, not just that it currently reports zero:

1. It really did run two independent generations with genuinely
   different model wording (otherwise a zero-divergence result would be
   vacuous -- of course two runs "agree" if nothing about them differs).
2. _fact_set/_compare_fact_sets genuinely detect a divergence when one
   exists, for each of the three things the WBS names separately
   (contributor list, counts, participation set) -- proven directly,
   without needing a second live generation to manufacture one.
3. The metric itself is registered as a hard zero (at_most 0), matching
   GC4/GC5/GC10's own "hard-zero, not a proportion" convention, since
   there is no acceptable rate of the same day's facts disagreeing with
   themselves.
"""

from __future__ import annotations

from p1.eval.cases import GoldenCaseRegistry
from p1.eval.chn16_cases import (
    _compare_fact_sets,
    _fact_set,
    _measure_gc9,
    register,
)
from p1.grounding.kernel import FactualLine
from p1.participation.ledger import ParticipationRecord
from p1.reporting.daily_summary import DailySummaryResult

# --- registration -----------------------------------------------------


def test_register_adds_gc9():
    registry = GoldenCaseRegistry()
    register(registry)
    assert {c.case_id for c in registry.all_cases()} == {"GC9"}


def test_registered_case_runs_via_the_registry():
    registry = GoldenCaseRegistry()
    register(registry)
    results = registry.get("GC9").measure_fn()
    assert len(results) == 1


# --- GC9: determinism of facts ------------------------------------------


def test_gc9_zero_divergences_across_two_real_generations():
    results = {r.metric_id: r for r in _measure_gc9()}
    divergence = results["GC9-fact-divergence-count"]
    assert divergence.comparator_name == "at_most"
    assert divergence.target == 0
    assert divergence.measured == 0
    assert divergence.passed is True


def test_gc9_target_is_a_hard_zero_not_a_proportion():
    results = {r.metric_id: r for r in _measure_gc9()}
    assert results["GC9-fact-divergence-count"].target == 0


def test_gc9_probe_is_not_vacuous_the_wording_really_differed():
    """If the two scripted gateways had drafted identical text, a zero
    divergence count would prove nothing. The detail line records that
    wording genuinely differed between the two generations -- proof the
    fact-set comparison is doing real work, not coasting on two
    identical runs."""
    results = {r.metric_id: r for r in _measure_gc9()}
    detail = results["GC9-fact-divergence-count"].detail
    assert "wording_differs=True" in detail


# --- _fact_set / _compare_fact_sets: direct unit tests ---------------------


def _result(section_lines: dict, participation: list[ParticipationRecord]) -> DailySummaryResult:
    return DailySummaryResult(
        channel_id="c1",
        date="2026-06-01",
        section_lines=section_lines,
        dropped={},
        participation=participation,
        content="",
    )


def _base_sections() -> dict:
    return {
        "what_moved": [FactualLine(text="a", message_id="m1"), FactualLine(text="b", message_id="m2")],
        "blockers": [FactualLine(text="c", message_id="m3")],
        "decisions": [],
        "questions": [],
    }


def test_compare_fact_sets_agrees_when_only_wording_differs():
    a = _result(
        {**_base_sections(), "what_moved": [FactualLine(text="wording one", message_id="m1"), FactualLine(text="wording two", message_id="m2")]},
        [ParticipationRecord(channel_id="c1", member_id="carol", date="2026-06-01", state="posted_no_update", evidence_message_ids=("m9",))],
    )
    b = _result(
        {**_base_sections(), "what_moved": [FactualLine(text="totally different phrasing", message_id="m1"), FactualLine(text="also different", message_id="m2")]},
        [ParticipationRecord(channel_id="c1", member_id="carol", date="2026-06-01", state="posted_no_update", evidence_message_ids=("m9",))],
    )
    assert _compare_fact_sets(_fact_set(a), _fact_set(b)) == []


def test_compare_fact_sets_flags_a_missing_contributor():
    a = _result(_base_sections(), [])
    dropped = _base_sections()
    dropped["what_moved"] = [dropped["what_moved"][0]]  # second generation lost m2
    b = _result(dropped, [])
    divergences = _compare_fact_sets(_fact_set(a), _fact_set(b))
    assert any("what_moved: contributor list differs" in d for d in divergences)
    assert any("what_moved: count differs" in d for d in divergences)


def test_compare_fact_sets_flags_a_participation_state_change():
    a = _result(
        _base_sections(),
        [ParticipationRecord(channel_id="c1", member_id="dave", date="2026-06-01", state="excluded", evidence_message_ids=())],
    )
    b = _result(
        _base_sections(),
        [ParticipationRecord(channel_id="c1", member_id="dave", date="2026-06-01", state="no_message", evidence_message_ids=())],
    )
    divergences = _compare_fact_sets(_fact_set(a), _fact_set(b))
    assert any("participation set differs" in d for d in divergences)


def test_compare_fact_sets_agrees_on_two_identical_fact_sets():
    a = _result(_base_sections(), [])
    b = _result(_base_sections(), [])
    assert _compare_fact_sets(_fact_set(a), _fact_set(b)) == []
