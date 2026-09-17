"""
CHN-18 golden case: GC6, publish idempotency.

The WBS row's own acceptance test: "Run the daily job three times over
the same day. Assert exactly one digest exists per channel, and that
the write log shows the two suppressed attempts." This exercises the
real production path end to end -- p1.publishing.daily_job.
run_daily_digest_job(), the same function scheduler.build_scheduler()
wires a real APScheduler CronTrigger to call -- against a channel that
has already published on an earlier day, so the first of the three
calls auto-approves and actually sends (CHN-17's own "subsequent days
run unattended" rule), and the second and third calls hit an
already-applied proposal.

This is the concrete case that drove daily_job.py's own design: an
earlier version of run_daily_digest_job() special-cased an
already-applied or rejected proposal by returning early WITHOUT calling
SPN-09's guarded_send() at all, on the reasoning that a routine,
expected rerun shouldn't spam write_log with a "refused" row every time
a scheduler fires on an already-decided day. That turned out to be the
wrong call: this row's acceptance test asks for exactly those two
reruns to be visible in write_log as suppressed attempts, which is only
possible if every call -- not just the first -- actually routes through
guarded_send(), since that is the one place in the codebase that ever
writes a write_log row. See DECISION_LOG.md.

Two metrics, matching the row's own two-part assertion:

  - GC6-digest-count -- exactly one digests row exists for this
    channel/day after three calls (CHN-13's own upsert-on-idempotency-key
    means regenerating content three times never triduplicates the row;
    this is a hard equals(1), not merely at_most).

  - GC6-suppressed-attempts -- exactly two write_log rows with
    status="refused" for this channel exist after three calls (the
    2nd and 3rd), alongside exactly one "sent" row (the 1st) -- checked
    as its own metric too, so a bug that suppressed ALL THREE calls
    (zero sent, three refused) would not slip past a check that only
    ever looked at the refused count.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

from p1.config.schema import ChannelConfig
from p1.eval.cases import GoldenCase, GoldenCaseRegistry, MetricResult, equals
from p1.publishing.daily_job import ALREADY_PUBLISHED, PUBLISHED, run_daily_digest_job
from p1.storage.db import get_connection, init_db
from p1.storage.digests_repo import DigestStore

CHANNEL_ID = "gc6-channel"
TODAY = date(2026, 6, 2)  # Tuesday
YESTERDAY = date(2026, 6, 1)  # Monday -- an already-published earlier day


def _config() -> ChannelConfig:
    return ChannelConfig(
        channel_id=CHANNEL_ID,
        display_name="GC6 Channel",
        allowlisted=True,
        roster=["alice"],
        update_window_start=time(9, 0),
        update_window_end=time(11, 0),
        timezone="UTC",
        working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        daily_digest_time=time(9, 0),
        weekly_digest_day="Fri",
        weekly_digest_time=time(16, 0),
        channel_owner_id="alice",
    )


class _NeverCalledGateway:
    """This channel has zero seeded messages, so generate_daily_summary
    must never call the model -- loud failure if that ever changes,
    same posture test_daily_job.py's own gateway double takes."""

    def generate(self, *args, **kwargs):
        raise AssertionError("gateway.generate() must not be called for a channel with no messages")


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        self.calls.append((channel_id, content))
        return {"ok": True}


@contextmanager
def _seeded_db():
    tmp_dir = tempfile.mkdtemp(prefix="chn18_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)",
                (CHANNEL_ID, "GC6 Channel"),
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_log_rows(db_path: str) -> list[dict]:
    conn = get_connection(db_path)
    try:
        return [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM write_log WHERE target = ? ORDER BY id", (CHANNEL_ID,)
            ).fetchall()
        ]
    finally:
        conn.close()


def _digest_row_count(db_path: str) -> int:
    conn = get_connection(db_path)
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM digests WHERE channel_id = ? AND date = ?",
            (CHANNEL_ID, TODAY.isoformat()),
        ).fetchone()["n"]
    finally:
        conn.close()


def _measure_gc6() -> list[MetricResult]:
    with _seeded_db() as db_path:
        config = _config()

        # Establish that this channel has already published once before
        # -- an ordinary already-onboarded channel, not a fresh one --
        # so today's run is the "subsequent days run unattended" case
        # (CHN-17), and every one of the three calls below reaches
        # guarded_send() with something to actually refuse or send.
        digest_store = DigestStore(db_path)
        digest_store.record(
            channel_id=CHANNEL_ID, date=YESTERDAY.isoformat(), type="daily",
            content="Yesterday's digest.", idempotency_key=f"{CHANNEL_ID}:{YESTERDAY.isoformat()}:daily",
        )
        digest_store.mark_published(
            idempotency_key=f"{CHANNEL_ID}:{YESTERDAY.isoformat()}:daily",
            published_at="2026-06-01T09:05:00+00:00",
        )

        publisher = _RecordingPublisher()
        results = [
            run_daily_digest_job(
                CHANNEL_ID, config, gateway=_NeverCalledGateway(), publisher=publisher,
                day=TODAY, db_path=db_path,
            )
            for _ in range(3)
        ]

        digest_count = _digest_row_count(db_path)
        write_log_rows = _write_log_rows(db_path)
        sent_rows = [row for row in write_log_rows if row["status"] == "sent"]
        refused_rows = [row for row in write_log_rows if row["status"] == "refused"]

    statuses = [r.status for r in results]

    return [
        MetricResult(
            metric_id="GC6-digest-count",
            name="digests row count for this channel/day after three job runs over the same day",
            measured=digest_count,
            target=1,
            comparator_name="equals",
            passed=equals(digest_count, 1),
            detail=(
                f"job statuses across the three runs: {statuses} "
                f"(expected [{PUBLISHED!r}, {ALREADY_PUBLISHED!r}, {ALREADY_PUBLISHED!r}])"
            ),
        ),
        MetricResult(
            metric_id="GC6-suppressed-attempts",
            name="write_log rows proving the 2nd and 3rd attempts were suppressed, alongside exactly one real send",
            measured={"sent": len(sent_rows), "refused": len(refused_rows)},
            target={"sent": 1, "refused": 2},
            comparator_name="equals",
            passed=equals({"sent": len(sent_rows), "refused": len(refused_rows)}, {"sent": 1, "refused": 2}),
            detail=(
                f"{len(write_log_rows)} write_log row(s) total for {CHANNEL_ID!r}: "
                f"{[(row['status'], json.loads(row['payload']).get('proposal_status')) for row in refused_rows]} "
                "is what the two suppressed reruns look like on camera"
            ),
        ),
    ]


def register(registry: GoldenCaseRegistry) -> None:
    registry.register(
        GoldenCase(
            case_id="GC6",
            description="Publish idempotency: three runs over the same day produce one digest and two suppressed write_log attempts (CHN-18)",
            measure_fn=_measure_gc6,
        )
    )
