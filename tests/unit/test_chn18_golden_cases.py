"""
CHN-18's own acceptance test: "Assertion passes and the suppressed
attempts are visible." This suite proves three things about GC6, not
just that it currently reports the right counts:

1. The scenario really does exercise all three outcomes a rerun can
   have -- one real send, then two refused reruns -- rather than, say,
   three refused runs with the "sent" count silently coming out zero
   too (a bug that a check only asserting refused==2 could miss
   entirely).
2. The two suppressed attempts are visible in write_log specifically as
   "refused" rows carrying the proposal's own status in their payload
   (proposal_status="applied") -- "on camera" in the same sense SPN-09's
   own docstring already claims, now actually proven true for a
   real rerun rather than merely asserted.
3. Both metrics are hard equals(), not proportions or at_most/at_least --
   there is no acceptable range for "roughly one digest" or "about two
   suppressed attempts."
"""

from __future__ import annotations

import json
from datetime import time as time_type

from p1.config.schema import ChannelConfig
from p1.eval.cases import GoldenCaseRegistry
from p1.eval.chn18_cases import (
    ALREADY_PUBLISHED,
    CHANNEL_ID,
    PUBLISHED,
    TODAY,
    YESTERDAY,
    _digest_row_count,
    _measure_gc6,
    _NeverCalledGateway,
    _RecordingPublisher,
    _seeded_db,
    _write_log_rows,
)
from p1.eval.chn18_cases import register as register_chn18
from p1.publishing.daily_job import run_daily_digest_job
from p1.storage.digests_repo import DigestStore

# --- registration -----------------------------------------------------


def test_register_adds_gc6():
    registry = GoldenCaseRegistry()
    register_chn18(registry)
    assert {c.case_id for c in registry.all_cases()} == {"GC6"}


def test_registered_case_runs_via_the_registry():
    registry = GoldenCaseRegistry()
    register_chn18(registry)
    results = registry.get("GC6").measure_fn()
    assert len(results) == 2


# --- GC6: publish idempotency --------------------------------------------


def test_gc6_exactly_one_digest_row_after_three_runs():
    results = {r.metric_id: r for r in _measure_gc6()}
    digest_count = results["GC6-digest-count"]
    assert digest_count.comparator_name == "equals"
    assert digest_count.target == 1
    assert digest_count.measured == 1
    assert digest_count.passed is True


def test_gc6_exactly_one_sent_and_two_refused_write_log_rows():
    results = {r.metric_id: r for r in _measure_gc6()}
    suppressed = results["GC6-suppressed-attempts"]
    assert suppressed.comparator_name == "equals"
    assert suppressed.target == {"sent": 1, "refused": 2}
    assert suppressed.measured == {"sent": 1, "refused": 2}
    assert suppressed.passed is True


def test_gc6_targets_are_hard_equals_not_a_proportion():
    results = {r.metric_id: r for r in _measure_gc6()}
    assert results["GC6-digest-count"].comparator_name == "equals"
    assert results["GC6-suppressed-attempts"].comparator_name == "equals"


def test_gc6_probe_is_not_vacuous_three_distinct_run_outcomes_occurred():
    """If a bug suppressed all three runs (or sent all three), the
    counts above could still coincidentally look plausible in
    isolation. The detail line records every run's actual JobResult
    status, so a regression that changed *which* runs were suppressed
    (not just how many) would still be visible here."""
    results = {r.metric_id: r for r in _measure_gc6()}
    detail = results["GC6-digest-count"].detail
    assert f"[{PUBLISHED!r}, {ALREADY_PUBLISHED!r}, {ALREADY_PUBLISHED!r}]" in detail


def _seed_channel_config() -> ChannelConfig:
    return ChannelConfig(
        channel_id=CHANNEL_ID, display_name="GC6 Channel", allowlisted=True, roster=["alice"],
        update_window_start=time_type(9, 0), update_window_end=time_type(11, 0), timezone="UTC",
        working_days=["Mon", "Tue", "Wed", "Thu", "Fri"], daily_digest_time=time_type(9, 0),
        weekly_digest_day="Fri", weekly_digest_time=time_type(16, 0), channel_owner_id="alice",
    )


def test_gc6_refused_rows_carry_the_applied_proposal_status_in_their_payload():
    """Directly inspects write_log, independent of _measure_gc6's own
    counting, so a bug in how the metric counts rows wouldn't also hide
    a bug in what those rows actually contain."""
    with _seeded_db() as db_path:
        config = _seed_channel_config()
        digest_store = DigestStore(db_path)
        digest_store.record(
            channel_id=CHANNEL_ID, date=YESTERDAY.isoformat(), type="daily", content="Yesterday's digest.",
            idempotency_key=f"{CHANNEL_ID}:{YESTERDAY.isoformat()}:daily",
        )
        digest_store.mark_published(
            idempotency_key=f"{CHANNEL_ID}:{YESTERDAY.isoformat()}:daily", published_at="2026-06-01T09:05:00+00:00",
        )
        publisher = _RecordingPublisher()
        for _ in range(3):
            run_daily_digest_job(
                CHANNEL_ID, config, gateway=_NeverCalledGateway(), publisher=publisher, day=TODAY, db_path=db_path,
            )

        refused = [row for row in _write_log_rows(db_path) if row["status"] == "refused"]

    assert len(refused) == 2
    for row in refused:
        assert json.loads(row["payload"])["proposal_status"] == "applied"


def test_gc6_digest_count_is_asserted_for_the_specific_channel_and_day_scoped():
    """_digest_row_count() is scoped to CHANNEL_ID/TODAY specifically --
    seeding yesterday's already-published digest in the same test db
    must never be counted toward today's row."""
    with _seeded_db() as db_path:
        DigestStore(db_path).record(
            channel_id=CHANNEL_ID, date=YESTERDAY.isoformat(), type="daily", content="Yesterday's digest.",
            idempotency_key=f"{CHANNEL_ID}:{YESTERDAY.isoformat()}:daily",
        )
        assert _digest_row_count(db_path) == 0  # nothing for TODAY yet
