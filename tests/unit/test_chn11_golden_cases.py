"""
CHN-11's own acceptance test: GC1 and GC2 register into SPN-07's harness,
GC1's precision/recall arithmetic is correct and precision-gated (not
recall), and GC2's exact-match assertion really is exact -- it must fail
on a spurious or missing member, not merely on a wrong proportion.

Run against the real, committed CHN-07 fixtures and seed/fixtures/labels.csv,
exactly like test_update_detection_against_fixtures.py and
test_participation_against_fixtures.py already do -- this is the same
hand-labelled ground truth, aggregated into the two named metrics
instead of individual asserts.
"""

from __future__ import annotations

from p1.eval.cases import GoldenCaseRegistry, equals
from p1.eval.chn11_cases import (
    _MESSAGE_BODY_RE,
    _load_rule_ground_truth,
    _measure_gc1,
    _measure_gc2,
    _PreciseScriptedGateway,
    register,
)

# --- registration -----------------------------------------------------


def test_register_adds_gc1_and_gc2():
    registry = GoldenCaseRegistry()
    register(registry)
    assert {c.case_id for c in registry.all_cases()} == {"GC1", "GC2"}


def test_registered_cases_run_via_the_registry():
    registry = GoldenCaseRegistry()
    register(registry)
    gc1_results = registry.get("GC1").measure_fn()
    gc2_results = registry.get("GC2").measure_fn()
    assert len(gc1_results) == 2
    assert len(gc2_results) == 3


# --- GC1: ground truth + precision/recall ------------------------------


def test_rule_ground_truth_has_the_expected_19_message_split():
    ground_truth = _load_rule_ground_truth()
    excluded = [mid for mid, expected in ground_truth.items() if expected]
    eligible = [mid for mid, expected in ground_truth.items() if not expected]

    assert sorted(excluded) == sorted(
        [
            "diff-bot-01",
            "diff-bot-02",
            "diff-sys-01",
            "diff-del-01",
            "diff-del-02",
            "diff-del-03",
            "diff-late-01",
            # CHN-28: previously-uncovered rules -- see DECISION_LOG.md.
            "diff-roster-01",
            "diff-threadoff-01",
            "diff-short-01",
        ]
    )
    assert sorted(eligible) == sorted(
        [
            "diff-edit-01",
            "diff-edit-02",
            "diff-edit-03",
            "diff-thread-01-reply-1",
            "diff-onbehalf-01",
            "diff-mention-01",
            "diff-depart-01",
            "diff-depart-02",
            "diff-depart-03",
        ]
    )


def test_thread_difficultys_root_message_is_not_scored():
    """Only the reply is this difficulty's planted claim; the root
    (priya.sharma's ordinary root question) is context, not a claim
    this metric asserts anything about."""
    ground_truth = _load_rule_ground_truth()
    assert "diff-thread-01-root" not in ground_truth
    assert ground_truth["diff-thread-01-reply-1"] is False


def test_gc1_measure_returns_precision_and_recall():
    results = {r.metric_id: r for r in _measure_gc1()}
    assert set(results) == {"GC1-precision", "GC1-recall"}

    precision = results["GC1-precision"]
    assert precision.target == 0.80
    assert precision.comparator_name == "at_least"
    assert precision.measured == 1.0  # true on the current fixtures/rules
    assert precision.passed is True

    recall = results["GC1-recall"]
    assert recall.target == 0.0
    assert recall.measured == 1.0
    assert recall.passed is True


def test_gc1_recall_target_never_gates_the_case_recall_is_reported_only():
    """GC1's WBS row gates precision at >=0.80 and only reports recall.
    That's implemented by giving the recall metric a target of 0.0 with
    an at_least comparator -- any real recall value (0.0 to 1.0) passes,
    so a low recall shows up in the printed/committed number without
    ever flipping the harness's overall all_passed."""
    results = {r.metric_id: r for r in _measure_gc1()}
    recall = results["GC1-recall"]
    assert recall.passed is True
    # the comparator itself would still correctly fail a genuinely
    # impossible value, proving this isn't just passed=True hardcoded:
    assert equals(recall.passed, recall.measured >= recall.target)


# --- GC2: exact match ---------------------------------------------------


def test_gc2_measure_matches_hand_verified_expected_sets():
    results = {r.metric_id: r for r in _measure_gc2()}
    assert set(results) == {
        "GC2-proj-alpha-2025-06-05",
        "GC2-proj-gamma-2025-06-05",
        "GC2-proj-beta-2025-06-11",
    }
    for result in results.values():
        assert result.comparator_name == "equals"
        assert result.passed is True, result.format_line()

    alpha = results["GC2-proj-alpha-2025-06-05"]
    assert alpha.measured == {
        "priya.sharma": "posted_no_update",
        "james.okafor": "no_message",
        "wei.chen": "posted_no_update",
        "fatima.hassan": "posted_no_update",
        "liam.oconnor": "excluded",
        "sara.johansson": "posted_no_update",
    }
    # all three participation states appear in this one channel/day,
    # per the WBS's "including the three participation states":
    assert set(alpha.measured.values()) == {"posted_no_update", "no_message", "excluded"}

    gamma = results["GC2-proj-gamma-2025-06-05"]
    assert "wei.chen" not in gamma.measured  # he's a genuine contributor this day

    beta = results["GC2-proj-beta-2025-06-11"]
    assert set(beta.measured) == {
        "james.okafor", "wei.chen", "diego.martinez",
        "amara.okonkwo", "kenji.tanaka", "elena.rossi", "sofia.almeida",
    }
    assert set(beta.measured.values()) == {"no_message"}


def test_gc2_style_exact_match_fails_on_a_spurious_extra_member():
    """The acceptance test is explicit: "an exact-set assertion, not a
    proportion." A set that gets everything right AND adds one member
    nobody asked about must still fail -- proving equals() is really
    being used here, not some partial/subset check."""
    expected = {"a": "no_message", "b": "excluded"}
    actual_with_extra = {"a": "no_message", "b": "excluded", "c": "no_message"}
    assert equals(actual_with_extra, expected) is False


def test_gc2_style_exact_match_fails_on_a_missing_member():
    expected = {"a": "no_message", "b": "excluded"}
    actual_missing_one = {"a": "no_message"}
    assert equals(actual_missing_one, expected) is False


def test_gc2_style_exact_match_fails_on_a_wrong_state():
    expected = {"a": "no_message", "b": "excluded"}
    actual_wrong_state = {"a": "no_message", "b": "posted_no_update"}
    assert equals(actual_wrong_state, expected) is False


# --- the scripted-gateway matching bug this module fixes ----------------


def test_precise_gateway_ignores_boilerplate_collisions_in_the_prompt():
    """The classifier prompt's own worked examples literally include the
    phrase 'Sounds good.' -- the exact text of DIFF-CHATTER-01's real
    organic message. A naive `if snippet in prompt` scripted gateway (as
    used elsewhere) would match that boilerplate on every single call,
    not just fatima.hassan's message. This gateway must only ever match
    the interpolated message body, never the instructional text around
    it."""
    prompt = (
        'Some instructions mentioning "Sounds good." as a worked example.\n\n'
        'Message to classify:\n"Deployed the export job to staging."'
    )
    gateway = _PreciseScriptedGateway({"Sounds good.": '{"label": "chatter", "confidence": 0.9}'})
    response = gateway.generate(prompt)
    assert response.text == '{"label": "update", "confidence": 0.9}'  # the default, not the canned trap


def test_precise_gateway_matches_the_real_message_body():
    prompt = 'Message to classify:\n"Sounds good."'
    gateway = _PreciseScriptedGateway({"Sounds good.": '{"label": "chatter", "confidence": 0.9}'})
    response = gateway.generate(prompt)
    assert response.text == '{"label": "chatter", "confidence": 0.9}'


def test_message_body_regex_extracts_only_the_final_quoted_section():
    prompt = 'Example: "Sounds good."\n\nMessage to classify:\n"Finished the auth flow."'
    match = _MESSAGE_BODY_RE.search(prompt)
    assert match.group(1) == "Finished the auth flow."