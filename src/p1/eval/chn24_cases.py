"""
CHN-24 golden cases: GC7, GC8, GC12.

GC7 -- nudge cap, never-nudge-excluded, and nudge-before-escalation
ordering, run end to end against the REAL run_nudge_job/run_escalation_job
(CHN-21/CHN-23), never a hand-simulated shortcut: a channel with an
excepted member (carol) and a non-responder (bob) who misses three
consecutive working days, with nudge_cap_per_day=1. Three metrics,
matching this row's own "<=cap / 0 / correct":

  - GC7-nudge-cap-holds -- the per-day nudge count actually SENT to bob
    never exceeds nudge_cap_per_day, checked against the real nudges
    table after each day's job is deliberately called three times (a
    scheduler-like rerun), not just once -- a cap that only ever holds
    because the job happened to run exactly once would not be a real
    guarantee.
  - GC7-excluded-never-nudged -- carol, on the exceptions list every
    single day, has zero rows in the nudges table at all, sent or not:
    she is never even a candidate, let alone sent to.
  - GC7-nudge-precedes-escalation -- bob's first nudge's sent_at is
    strictly earlier than his escalation's sent_at, read back from the
    real nudges/escalations tables -- an independent recomputation from
    the stored timestamps, not a trust of whatever order the job calls
    happened to run in.

GC8 -- approval enforcement, "tested directly against the service
layer, not through the interface": for each of the three action types
this programme ever writes with (channel_post, nudge, escalation), a
proposal is created directly via SPN-08's ProposalStore and left
pending, or created and then rejected -- SPN-09's guarded_send() is
then called on it DIRECTLY, never through run_daily_digest_job/
run_nudge_job/run_escalation_job, with a send_fn that raises if it is
ever invoked. All six calls (3 action types x 2 statuses) must raise
WriteRefusedError before send_fn runs at all.

GC12 -- configuration is really configuration: the exact same two
messages, on the exact same day, are classified and ledgered twice --
once under a config with roster=[alice,bob] and update window
09:00-11:00, once under a config with roster=[alice,bob,carol] and a
narrower window 09:00-10:00. bob's message (posted at 10:30) is a
genuine update inside the first window but falls outside the second,
so he moves from "contributor" to "posted_no_update" purely because
the window changed; carol, newly added to the roster in the second
config and never posting, moves from "not on this channel at all" to
"no_message" purely because the roster changed. Neither participation.py
nor detection/rules.py is touched to make this happen -- the WBS row's
own point is that changing configuration, and nothing else, moves the
non-responder set.
"""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

from p1.adapters.teams_reader import TeamsMessage
from p1.approval.proposals import ProposalStore
from p1.approval.write_guard import WriteRefusedError, guarded_send
from p1.config.schema import ChannelConfig
from p1.detection.pipeline import classify_and_persist
from p1.escalations.escalation_job import run_escalation_job
from p1.eval.cases import GoldenCase, GoldenCaseRegistry, MetricResult, at_most, equals
from p1.llm.gateway import LLMResponse
from p1.nudges.nudge_job import run_nudge_job
from p1.participation.ledger import NO_MESSAGE, POSTED_NO_UPDATE, build_ledger
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.escalations_repo import EscalationStore
from p1.storage.messages_repo import MessageStore
from p1.storage.nudges_repo import NudgeStore

# --- GC7: nudge cap, never-nudge-excluded, nudge-before-escalation --------

GC7_CHANNEL_ID = "gc7-channel"
GC7_FRI_PREV = date(2026, 5, 29)  # the working day just before GC7_MON
GC7_MON = date(2026, 6, 1)
GC7_TUE = date(2026, 6, 2)
GC7_WED = date(2026, 6, 3)


def _gc7_config() -> ChannelConfig:
    return ChannelConfig(
        channel_id=GC7_CHANNEL_ID,
        display_name="GC7 Channel",
        roster=["alice", "bob", "carol"],
        update_window_start=time(9, 0),
        update_window_end=time(11, 0),
        timezone="UTC",
        working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        daily_digest_time=time(9, 0),
        weekly_digest_day="Fri",
        weekly_digest_time=time(16, 0),
        channel_owner_id="priya",
        exceptions=[{"member_id": "carol", "reason": "On leave"}],
        nudge_enabled=True,
        nudge_cap_per_day=1,
        escalation_threshold_days=3,
    )


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def post_direct_message(self, member_id: str, content: str) -> dict:
        self.calls.append((member_id, content))
        return {"ok": True}


def _gc7_seed_message(db_path: str, message_id: str, author_id: str, day: date) -> None:
    MessageStore(db_path).upsert_messages(
        [
            TeamsMessage(
                id=message_id, channel_id=GC7_CHANNEL_ID, author_id=author_id,
                posted_at=f"{day.isoformat()}T09:30:00+00:00", body="text",
            )
        ]
    )
    ClassificationStore(db_path).record(message_id=message_id, label="update", method="model", confidence=0.9)


@contextmanager
def _gc7_seeded_db():
    tmp_dir = tempfile.mkdtemp(prefix="chn24_gc7_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'GC7 Channel', 1)",
                (GC7_CHANNEL_ID,),
            )
            for member_id in ("alice", "bob", "carol", "priya"):
                conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
            conn.commit()
        finally:
            conn.close()
        yield db_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _run_gc7_scenario(db_path: str) -> tuple[ChannelConfig, _RecordingPublisher]:
    config = _gc7_config()
    publisher = _RecordingPublisher()
    proposal_store = ProposalStore(db_path)
    nudge_store = NudgeStore(db_path)
    escalation_store = EscalationStore(db_path)

    # alice always contributes. bob and carol are silent every day from
    # GC7_MON -- but bob ALSO gets one anchor contribution on the working
    # day just before the window: _streak_dates_ending_at() walks
    # backward for real, and an empty fixture with literally no messages
    # before GC7_MON would otherwise look like an unbroken run of missed
    # days stretching indefinitely into the past, pushing bob's real
    # streak_start_date arbitrarily far back instead of GC7_MON -- the
    # exact fixture-completeness issue CHN-23's own test file first hit
    # and fixed the same way. carol needs no anchor: she is on the
    # exceptions list throughout, so her streak is never walked at all.
    _gc7_seed_message(db_path, "anchor-alice", "alice", GC7_FRI_PREV)
    _gc7_seed_message(db_path, "anchor-bob", "bob", GC7_FRI_PREV)
    for d in (GC7_MON, GC7_TUE, GC7_WED):
        _gc7_seed_message(db_path, f"alice-{d.isoformat()}", "alice", d)

    def _run_nudges(day: date, times: int) -> None:
        for _ in range(times):
            run_nudge_job(
                GC7_CHANNEL_ID, config, publisher, day=day, db_path=db_path,
                proposal_store=proposal_store, nudge_store=nudge_store,
            )

    # MON: bob's first nudge ever -- three reruns before approval prove
    # the cap holds even under repeated scheduler-like attempts, not
    # just because the job happened to run once.
    _run_nudges(GC7_MON, times=3)
    bob_mon = proposal_store.get_by_idempotency_key(f"{GC7_CHANNEL_ID}:bob:{GC7_MON.isoformat()}:1")
    proposal_store.approve(bob_mon.id, approver_id="priya")
    _run_nudges(GC7_MON, times=1)

    # TUE, WED: bob is now a previously-nudged person -- each day's
    # nudge auto-approves and sends unattended. Three reruns per day
    # again, same reason as MON.
    _run_nudges(GC7_TUE, times=3)
    _run_nudges(GC7_WED, times=3)

    # WED: bob's 3-day streak reaches the escalation threshold, and he
    # has already been nudged -- first escalation ever: create pending,
    # approve, resend.
    run_escalation_job(
        GC7_CHANNEL_ID, config, publisher, day=GC7_WED, db_path=db_path,
        proposal_store=proposal_store, escalation_store=escalation_store, nudge_store=nudge_store,
    )
    bob_escalation = proposal_store.get_by_idempotency_key(f"{GC7_CHANNEL_ID}:bob:{GC7_MON.isoformat()}")
    proposal_store.approve(bob_escalation.id, approver_id="priya")
    run_escalation_job(
        GC7_CHANNEL_ID, config, publisher, day=GC7_WED, db_path=db_path,
        proposal_store=proposal_store, escalation_store=escalation_store, nudge_store=nudge_store,
    )

    return config, publisher


def _measure_gc7() -> list[MetricResult]:
    with _gc7_seeded_db() as db_path:
        config, _publisher = _run_gc7_scenario(db_path)

        conn = get_connection(db_path)
        try:
            bob_nudge_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT date, sent_at FROM nudges WHERE channel_id = ? AND member_id = 'bob' "
                    "ORDER BY id",
                    (GC7_CHANNEL_ID,),
                ).fetchall()
            ]
            carol_nudge_count = conn.execute(
                "SELECT COUNT(*) AS n FROM nudges WHERE channel_id = ? AND member_id = 'carol'",
                (GC7_CHANNEL_ID,),
            ).fetchone()["n"]
            bob_escalation_row = conn.execute(
                "SELECT sent_at FROM escalations WHERE channel_id = ? AND member_id = 'bob' AND sent_at IS NOT NULL",
                (GC7_CHANNEL_ID,),
            ).fetchone()
        finally:
            conn.close()

    per_day_sent_counts: dict[str, int] = {}
    for row in bob_nudge_rows:
        if row["sent_at"] is not None:
            per_day_sent_counts[row["date"]] = per_day_sent_counts.get(row["date"], 0) + 1
    max_per_day = max(per_day_sent_counts.values()) if per_day_sent_counts else 0

    bob_sent_ats = sorted(row["sent_at"] for row in bob_nudge_rows if row["sent_at"] is not None)
    first_nudge_sent_at = bob_sent_ats[0] if bob_sent_ats else None
    escalation_sent_at = bob_escalation_row["sent_at"] if bob_escalation_row else None
    order_correct = (
        first_nudge_sent_at is not None
        and escalation_sent_at is not None
        and first_nudge_sent_at < escalation_sent_at
    )

    return [
        MetricResult(
            metric_id="GC7-nudge-cap-holds",
            name="nudges actually sent to bob never exceed nudge_cap_per_day, any day, even under reruns",
            measured=max_per_day,
            target=config.nudge_cap_per_day,
            comparator_name="at_most",
            passed=at_most(max_per_day, config.nudge_cap_per_day),
            detail=f"per-day sent counts: {per_day_sent_counts} (each day's job called 3x before/at approval)",
        ),
        MetricResult(
            metric_id="GC7-excluded-never-nudged",
            name="carol (on the exceptions list every day) has zero nudge rows of any kind",
            measured=carol_nudge_count,
            target=0,
            comparator_name="equals",
            passed=equals(carol_nudge_count, 0),
            detail="she is never even a candidate, let alone sent to, across all 3 days",
        ),
        MetricResult(
            metric_id="GC7-nudge-precedes-escalation",
            name="bob's first sent nudge precedes his sent escalation",
            measured=order_correct,
            target=True,
            comparator_name="equals",
            passed=equals(order_correct, True),
            detail=f"first nudge sent_at={first_nudge_sent_at!r}, escalation sent_at={escalation_sent_at!r}",
        ),
    ]


# --- GC8: approval enforcement, tested directly against the service layer -

GC8_CHANNEL_ID = "gc8-channel"

_GC8_CASES: tuple[tuple[str, str], ...] = (
    ("channel_post", GC8_CHANNEL_ID),
    ("nudge", "alice"),
    ("escalation", "priya"),
)


@contextmanager
def _gc8_seeded_db():
    tmp_dir = tempfile.mkdtemp(prefix="chn24_gc8_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'GC8 Channel', 1)",
                (GC8_CHANNEL_ID,),
            )
            for member_id in ("alice", "priya"):
                conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
            conn.commit()
        finally:
            conn.close()
        yield db_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _gc8_refused(proposal_store: ProposalStore, proposal_id: str, action_type: str, target: str, db_path: str) -> bool:
    """True iff guarded_send() raised WriteRefusedError WITHOUT ever
    calling send_fn -- called directly here, never through
    run_daily_digest_job/run_nudge_job/run_escalation_job, per this
    row's own "tested directly against the service layer, not through
    the interface" acceptance test."""

    def _never_called():
        raise AssertionError(
            f"send_fn must never be called for proposal_id={proposal_id!r} (action_type={action_type!r})"
        )

    try:
        guarded_send(
            proposal_id, action_type=action_type, target=target, send_fn=_never_called,
            store=proposal_store, db_path=db_path,
        )
    except WriteRefusedError:
        return True
    return False


def _measure_gc8() -> list[MetricResult]:
    results = []
    with _gc8_seeded_db() as db_path:
        proposal_store = ProposalStore(db_path)
        for action_type, target in _GC8_CASES:
            for status_name in ("pending", "rejected"):
                idempotency_key = f"gc8:{action_type}:{status_name}"
                proposal = proposal_store.create(
                    type=action_type, payload={"gc8": True}, original_model_output={"gc8": True},
                    source_refs=[], idempotency_key=idempotency_key,
                )
                if status_name == "rejected":
                    proposal_store.reject(proposal.id, approver_id="priya")

                refused = _gc8_refused(proposal_store, proposal.id, action_type, target, db_path)
                results.append(
                    MetricResult(
                        metric_id=f"GC8-{action_type}-{status_name}",
                        name=f"{action_type} from a {status_name} proposal is refused at the service layer",
                        measured=refused,
                        target=True,
                        comparator_name="equals",
                        passed=equals(refused, True),
                        detail=(
                            f"guarded_send() called directly (never through the job interface) "
                            f"for proposal_id={proposal.id!r}, status={status_name!r}"
                        ),
                    )
                )
    return results


# --- GC12: configuration is really configuration ---------------------------

GC12_CHANNEL_ID = "gc12-channel"
GC12_DAY = date(2026, 6, 1)  # Monday


def _gc12_config_a() -> ChannelConfig:
    return ChannelConfig(
        channel_id=GC12_CHANNEL_ID,
        display_name="GC12 Channel",
        roster=["alice", "bob"],
        update_window_start=time(9, 0),
        update_window_end=time(11, 0),
        timezone="UTC",
        working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        daily_digest_time=time(9, 0),
        weekly_digest_day="Fri",
        weekly_digest_time=time(16, 0),
        channel_owner_id="alice",
    )


def _gc12_config_b() -> ChannelConfig:
    return ChannelConfig(
        channel_id=GC12_CHANNEL_ID,
        display_name="GC12 Channel",
        roster=["alice", "bob", "carol"],  # roster changed: carol added
        update_window_start=time(9, 0),
        update_window_end=time(10, 0),  # window narrowed: 09:00-10:00, was 09:00-11:00
        timezone="UTC",
        working_days=["Mon", "Tue", "Wed", "Thu", "Fri"],
        daily_digest_time=time(9, 0),
        weekly_digest_day="Fri",
        weekly_digest_time=time(16, 0),
        channel_owner_id="alice",
    )


class _AlwaysUpdateGateway:
    """Every eligible (non-rule-settled) message is a genuine update --
    this fixture's whole point is that whether a message COUNTS is
    decided entirely by config (roster membership, the update window),
    never by content, so the classifier's own opinion is held constant
    on purpose."""

    def generate(self, prompt, **kwargs):
        return LLMResponse(
            text='{"label": "update", "confidence": 0.9}',
            provider="fake", model="fake-model",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


@contextmanager
def _gc12_seeded_db():
    tmp_dir = tempfile.mkdtemp(prefix="chn24_gc12_")
    try:
        db_path = str(Path(tmp_dir) / "eval.db")
        init_db(db_path)
        conn = get_connection(db_path)
        try:
            conn.execute(
                "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'GC12 Channel', 1)",
                (GC12_CHANNEL_ID,),
            )
            for member_id in ("alice", "bob", "carol"):
                conn.execute("INSERT INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
            conn.commit()
        finally:
            conn.close()

        # bob's message is posted at 10:30 -- a genuine update inside
        # config A's 09:00-11:00 window, but outside config B's
        # narrower 09:00-10:00 window. carol never posts at all.
        messages = [
            TeamsMessage(
                id="gc12-alice-1", channel_id=GC12_CHANNEL_ID, author_id="alice",
                posted_at=f"{GC12_DAY.isoformat()}T09:30:00+00:00", body="Here is my update for today, on track.",
            ),
            TeamsMessage(
                id="gc12-bob-1", channel_id=GC12_CHANNEL_ID, author_id="bob",
                posted_at=f"{GC12_DAY.isoformat()}T10:30:00+00:00",
                body="Here is my update for today too, also on track.",
            ),
        ]
        MessageStore(db_path).upsert_messages(messages)
        yield db_path, messages
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _measure_gc12() -> list[MetricResult]:
    with _gc12_seeded_db() as (db_path, messages):
        gateway = _AlwaysUpdateGateway()

        config_a = _gc12_config_a()
        classify_and_persist(messages, config_a, gateway, db_path=db_path)
        ledger_a = {r.member_id: r.state for r in build_ledger(GC12_CHANNEL_ID, GC12_DAY, config_a, db_path=db_path)}

        # Reclassifying the SAME message objects under config B replaces
        # each message's classifications row in place (ClassificationStore.
        # record() upserts on message_id) -- this is the same raw data,
        # re-evaluated under different configuration, not a different
        # scenario.
        config_b = _gc12_config_b()
        classify_and_persist(messages, config_b, gateway, db_path=db_path)
        ledger_b = {r.member_id: r.state for r in build_ledger(GC12_CHANNEL_ID, GC12_DAY, config_b, db_path=db_path)}

    expected_a: dict[str, str] = {}  # alice and bob both contribute; carol isn't on this roster
    expected_b = {"bob": POSTED_NO_UPDATE, "carol": NO_MESSAGE}

    return [
        MetricResult(
            metric_id="GC12-config-a-non-responders",
            name="non-responder set under config A (roster=[alice,bob], window 09:00-11:00)",
            measured=ledger_a,
            target=expected_a,
            comparator_name="equals",
            passed=equals(ledger_a, expected_a),
            detail="bob's 10:30 update is inside this window, so he -- like alice -- is a contributor",
        ),
        MetricResult(
            metric_id="GC12-config-b-non-responders",
            name="non-responder set under config B (roster=[alice,bob,carol], window 09:00-10:00)",
            measured=ledger_b,
            target=expected_b,
            comparator_name="equals",
            passed=equals(ledger_b, expected_b),
            detail="bob's same 10:30 message now falls outside the window; carol is new to the roster",
        ),
        MetricResult(
            metric_id="GC12-set-moves-with-config",
            name="the non-responder set actually differs between the two configs, on identical underlying data",
            measured=(ledger_a != ledger_b),
            target=True,
            comparator_name="equals",
            passed=equals(ledger_a != ledger_b, True),
            detail=f"config A: {ledger_a} vs config B: {ledger_b}",
        ),
    ]


def register(registry: GoldenCaseRegistry) -> None:
    registry.register(
        GoldenCase(
            case_id="GC7",
            description="Nudge cap, never-nudge-excluded, nudge-before-escalation ordering, run end to end (CHN-24)",
            measure_fn=_measure_gc7,
        )
    )
    registry.register(
        GoldenCase(
            case_id="GC8",
            description="Approval enforcement for nudge/escalation/channel_post, tested directly at the service layer (CHN-24)",
            measure_fn=_measure_gc8,
        )
    )
    registry.register(
        GoldenCase(
            case_id="GC12",
            description="Configuration is really configuration: roster and window changes move the non-responder set (CHN-24)",
            measure_fn=_measure_gc12,
        )
    )
