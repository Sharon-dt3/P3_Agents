"""
CHN-12's own acceptance test: GC5 and GC10 register into SPN-07's
harness, and both are the hard pass/fail assertions the WBS row calls
for -- "both are hard-zero assertions rather than proportions" -- not
some proportion or ratio that could partially pass.

GC5 exercises the real production factory (p1.adapters.factory.
get_teams_reader()) against the real committed fixtures, so it needs no
hand-built ground truth: the invariant under test is architectural
(scope-filtered ingestion never touches an out-of-scope channel at
all), and is checked directly against the real config/channels/*.yaml
allowlist.

GC10 is a synthetic two-delta-run scenario (the committed fixtures have
no distinct before/after snapshot to exercise an edit or delete
against), built the same way test_ingestion_sync.py's own tests already
build one: a second reader constructed from "run 1's messages plus more
appended at the end," sharing one persisted delta token across two
sync_channel() calls.
"""

from __future__ import annotations

from p1.eval.cases import GoldenCaseRegistry, equals
from p1.eval.chn12_cases import (
    CHAT_GROUP,
    CHAT_ONE_TO_ONE,
    GAMMA,
    _measure_gc5,
    _measure_gc10,
    register,
)

# --- registration -----------------------------------------------------


def test_register_adds_gc5_and_gc10():
    registry = GoldenCaseRegistry()
    register(registry)
    assert {c.case_id for c in registry.all_cases()} == {"GC5", "GC10"}


def test_registered_cases_run_via_the_registry():
    registry = GoldenCaseRegistry()
    register(registry)
    gc5_results = registry.get("GC5").measure_fn()
    gc10_results = registry.get("GC10").measure_fn()
    assert len(gc5_results) == 4
    assert len(gc10_results) == 6


# --- GC5: scope gate hard zero ------------------------------------------


def test_gc5_zero_out_of_scope_messages_after_a_full_ingest():
    results = {r.metric_id: r for r in _measure_gc5()}
    count = results["GC5-out-of-scope-message-count"]
    assert count.comparator_name == "at_most"
    assert count.target == 0
    assert count.measured == 0
    assert count.passed is True


def test_gc5_targets_and_comparators_are_hard_not_proportional():
    """The WBS is explicit: "hard-zero assertions rather than
    proportions." None of GC5's targets are a ratio or a percentage --
    the count metric targets a literal 0 and the refusal metrics target
    a literal True, never anything in between."""
    results = {r.metric_id: r for r in _measure_gc5()}
    for result in results.values():
        assert result.target in (0, True)


def test_gc5_direct_refusal_proofs_all_pass():
    results = {r.metric_id: r for r in _measure_gc5()}

    gamma = results["GC5-gamma-channel-refused"]
    assert gamma.measured is True
    assert gamma.passed is True
    assert f"channel_id={GAMMA!r}" in gamma.detail

    one_to_one = results["GC5-one-to-one-chat-refused"]
    assert one_to_one.measured is True
    assert one_to_one.passed is True
    assert f"channel_id={CHAT_ONE_TO_ONE!r}" in one_to_one.detail

    group = results["GC5-group-chat-refused"]
    assert group.measured is True
    assert group.passed is True
    assert f"channel_id={CHAT_GROUP!r}" in group.detail


def test_gc5_chat_ids_use_the_unq_gbl_spaces_shape():
    """Same id shape test_scope_gate.py's own chat-id check already
    uses -- these are never configured channels, so they were never on
    the allowlist to begin with."""
    assert CHAT_ONE_TO_ONE.endswith("@unq.gbl.spaces")
    assert CHAT_GROUP.endswith("@unq.gbl.spaces")
    assert CHAT_ONE_TO_ONE != CHAT_GROUP


# --- GC10: ingest correctness across two delta runs -----------------------


def test_gc10_message_count_is_seven_not_nine():
    """5 ids from run 1 + 2 brand-new ids from run 2 = 7 stored rows --
    not 9, which is what you'd get if the resent edit/delete had been
    treated as new messages instead of updates to their existing rows."""
    results = {r.metric_id: r for r in _measure_gc10()}
    count = results["GC10-message-count"]
    assert count.comparator_name == "equals"
    assert count.target == 7
    assert count.measured == 7
    assert count.passed is True


def test_gc10_edit_preserves_posted_at_and_updates_content():
    results = {r.metric_id: r for r in _measure_gc10()}

    preserved = results["GC10-edit-posted-at-preserved"]
    assert preserved.measured is True
    assert preserved.passed is True

    updated = results["GC10-edit-content-updated"]
    assert updated.measured is True
    assert updated.passed is True


def test_gc10_delete_is_flagged_with_deleted_at_and_unchanged_posted_at():
    results = {r.metric_id: r for r in _measure_gc10()}
    delete_result = results["GC10-delete-handled"]
    assert delete_result.measured is True
    assert delete_result.passed is True


def test_gc10_bot_and_system_flags_correct_across_both_runs():
    results = {r.metric_id: r for r in _measure_gc10()}

    bot_flags = results["GC10-bot-flags-correct"]
    assert bot_flags.comparator_name == "equals"
    assert bot_flags.passed is True
    assert bot_flags.measured["gc10-bot-1"] is True
    assert bot_flags.measured["gc10-bot-2"] is True
    assert bot_flags.measured["gc10-m1"] is False
    assert bot_flags.measured["gc10-sys-1"] is False

    system_flags = results["GC10-system-flags-correct"]
    assert system_flags.comparator_name == "equals"
    assert system_flags.passed is True
    assert system_flags.measured["gc10-sys-1"] is True
    assert system_flags.measured["gc10-sys-2"] is True
    assert system_flags.measured["gc10-m1"] is False
    assert system_flags.measured["gc10-bot-1"] is False


def test_gc10_style_exact_match_fails_on_a_single_wrong_flag():
    """Proves equals() is really doing exact-map comparison here, not a
    proportion that would still mostly pass with one flag wrong."""
    expected = {"a": True, "b": False}
    actual_one_wrong = {"a": True, "b": True}
    assert equals(actual_one_wrong, expected) is False


def test_gc10_targets_are_hard_not_proportional():
    results = {r.metric_id: r for r in _measure_gc10()}
    for metric_id in (
        "GC10-edit-posted-at-preserved",
        "GC10-edit-content-updated",
        "GC10-delete-handled",
    ):
        assert results[metric_id].target is True
