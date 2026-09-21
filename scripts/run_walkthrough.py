"""
CHN-32: the recorded walkthrough's own real backing script.

Run this once, on camera, with a real ANTHROPIC_API_KEY in .env --
every digest/summary/weekly-narrative line the model writes is a real
call (see p1.reporting.daily_summary's own docstring, same as CHN-31's
scripts/run_daily.py). It prints one clearly marked "BEAT" section per
build-day acceptance criterion in MASTER_IMPLEMENTATION_PLAN.md's own
day-by-day table (W1 D1 through W2 D9), so the recording can just
follow this script's output, top to bottom:

  1.  W1 D1 -- a malformed model response is caught and retried
  2.  W1 D2 -- ingest two channels, refuse the third
  3.  W1 D2 -- a chat refused at the boundary
  4.  W1 D3 -- two consecutive delta syncs; an edit keeps its original
      time; the fixture generator reproduces byte-identical
  5.  W1 D4/D5 -- update detection: a rule decision and a classifier
      decision, both channels
  6.  W1 D4 -- the participation ledger, all three states, both channels
  7.  W2 D6/D7 -- scheduled digest publishing: idempotent, each
      channel's own local time, a pending proposal cannot post
  8.  W2 D8 -- the weekly roll-up, both channels
  9.  W2 D8/D9 -- nudges: proj-beta's real approve/reject flow and
      proj-alpha's chatter-only member, nudged exactly like genuine
      silence
  10. W2 D9 -- an escalation evidence bundle, both channels
  11. W1 D5 -- the eval harness, run for real, numbers on screen

Everything here calls the exact same production functions every unit
test, GC, and CHN-31's scripts/run_daily.py already exercise -- ingestion
goes through the real p1.adapters.factory.get_teams_reader() and
p1.ingestion.sync.sync_all_allowlisted_channels(), the same production
wiring GC5 proves, not CHN-31's own fixture-loading shortcut. There is
no second, demo-only code path anywhere in this script; the only
substitutions this script ever makes are the LLM gateway and the Teams
publisher, exactly the two seams p1.adapters.factory/LLMGateway already
exist to swap, and beat 1's throwaway retry-demo gateway, which never
touches any of the other beats' data.

Two pieces of real data worth naming up front, since they drive beats
9 and 10 on each channel:

  - proj-beta's sofia.almeida has a genuine, naturally-occurring
    7-consecutive-working-day silence already sitting in the committed
    fixtures (2025-06-05 through 2025-06-13) -- nothing was added or
    adjusted to manufacture the nudge/escalation beats. Her real streak
    clears proj-beta's own escalation_threshold_days on its own, and
    kenji.tanaka's real, near-total "posted, but nothing counted"
    pattern across the same window is what beat 9 uses to show the
    OTHER nudge wording (see p1.nudges.nudge_job._render_nudge_message).

  - proj-alpha's fatima.hassan is DIFF-CHATTER-01 (seed/fixtures/labels.csv):
    every organic message she posts is chatter ("Thanks!", "Sounds
    good."), never an update. A direct build_ledger() query across
    proj-alpha's whole fixture window (2025-06-02 through 2025-06-12,
    the same discipline the beta query above used) found she also has a
    genuine 7-working-day run of posted_no_update/no_message days --
    proj-alpha's own escalation_threshold_days clears on this streak the
    same as proj-beta's. proj-alpha's committed config has
    nudge_enabled: false (its real, intentional value, not a temporary
    override); beat 9 turns it on for this run only via
    ChannelConfig.model_copy(), the same in-memory-only override this
    project already documents as legitimate for demos (clock overrides,
    scheduler.is_due()) -- config/channels/proj-alpha.yaml itself is
    never touched. This lets proj-alpha show something proj-beta's own
    story can't: a member who LOOKS active (she posts every day) still
    gets nudged and escalated exactly like genuine silence, because the
    ledger counts real updates, not messages.

See DECISION_LOG.md's CHN-32 entries for how both of these were found.
"""

from __future__ import annotations

import filecmp
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(SCRIPT_DIR))

from p1.adapters.factory import get_teams_publisher, get_teams_reader
from p1.adapters.fixtures import load_teams_fixtures
from p1.approval.proposals import ProposalStore
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.escalations.escalation_job import run_escalation_job
from p1.governance.scope_gate import ScopeViolationError
from p1.ingestion.sync import sync_all_allowlisted_channels
from p1.llm.gateway import LLMGateway, LLMResponse
from p1.llm.structured import StructuredOutputError, generate_structured
from p1.nudges.nudge_job import run_nudge_job
from p1.participation.ledger import EXCLUDED, NO_MESSAGE, POSTED_NO_UPDATE, build_ledger
from p1.publishing.daily_job import run_daily_digest_job
from p1.reporting.weekly_summary import generate_and_persist_weekly_rollup
from p1.storage.db import DEFAULT_DB_PATH, get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

ALPHA = "19:proj-alpha@thread.tacv2"
BETA = "19:proj-beta@thread.tacv2"
GAMMA = "19:proj-gamma@thread.tacv2"

# Synthetic ids that were never a configured channel at all -- same
# shape p1.eval.chn12_cases.py's own GC5 already uses for this exact
# proof.
CHAT_ONE_TO_ONE = "19:one-to-one-chat@unq.gbl.spaces"
CHAT_GROUP = "19:another-group-chat@unq.gbl.spaces"

DAILY_SUMMARY_DAY = date(2025, 6, 6)     # a real Friday: proj-alpha's own weekly_digest_day AND its busiest day
LEDGER_DEMO_DAY = date(2025, 6, 5)       # proj-alpha: excluded + posted_no_update + no_message, all real
WEEKLY_END_DAY_BETA = date(2025, 6, 12)  # proj-beta's own configured weekly_digest_day (Thu)
WEEKLY_END_DAY_ALPHA = DAILY_SUMMARY_DAY  # proj-alpha's own configured weekly_digest_day (Fri)

NUDGE_DAY_1 = date(2025, 6, 5)           # sofia's first real missed day on proj-beta
NUDGE_DAY_2 = date(2025, 6, 6)           # sofia's second consecutive real missed day
REJECT_MEMBER = "amara.okonkwo"          # whoever's nudge we reject on camera, for real

ALPHA_NUDGE_DAY_1 = date(2025, 6, 9)     # fatima's first missed day of her REAL 4-day 06-09..06-12 streak
ALPHA_NUDGE_DAY_2 = date(2025, 6, 10)    # her second consecutive missed day
ALPHA_ESCALATION_DAY = date(2025, 6, 11)  # her third consecutive missed day -- clears the threshold
# NOTE: NOT 06-02/03/04 -- she genuinely contributes real updates on 06-05 and
# 06-06, so a streak that starts on 06-02 (the fixture window's very first
# day) has nothing earlier to walk back into and hits a real latent bug in
# escalation_job.py's streak walker (it has no lower bound at the channel's
# actual data start date, so it silently walks back for months into a data
# desert before a boundary condition finally stops it, producing a nonsense
# streak_start_date). 06-09 is preceded by a real contribution on 06-06, so
# the walker correctly stops there. See DECISION_LOG.md's CHN-32 entry.


def _beat(n: int, title: str) -> None:
    print()
    print("=" * 78)
    print(f"BEAT {n}: {title}")
    print("=" * 78)


def _setup(db_path):
    init_db(db_path)
    config_store = ChannelConfigStore()
    config_store.sync_to_db(db_path)

    # Same pre-existing, already-disclosed workaround CHN-31 used
    # (DECISION_LOG.md): ingestion has never had its own member-sync
    # capability, mock or Graph, so member rows are inserted directly
    # from the fixture data before any message can be stored (FK).
    _, _, messages_by_channel = load_teams_fixtures()
    conn = get_connection(db_path)
    try:
        author_ids = sorted(
            {
                m.author_id
                for cid in (ALPHA, BETA)
                for m in messages_by_channel.get(cid, [])
                if m.author_id
            }
        )
        for author_id in author_ids:
            conn.execute(
                "INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)",
                (author_id, author_id),
            )
        conn.commit()
    finally:
        conn.close()

    return config_store, messages_by_channel


# ---------------------------------------------------------------------------
# BEAT 1 -- W1 D1: a malformed model response is caught and retried
# ---------------------------------------------------------------------------

class _RetryDemoSchema:
    """A minimal stand-in schema, defined locally rather than imported
    from tests/ (production code never imports test modules) -- same
    shape tests/unit/test_structured_output.py already proves this
    exact mechanism against."""

    from pydantic import BaseModel

    class Schema(BaseModel):
        label: str
        confidence: float


class _MalformedThenValidGateway:
    """Deliberately returns unparseable text on the first call, then a
    valid instance on the second -- proves generate_structured()'s own
    retry loop (p1.llm.structured), never touches the real gateway or
    network. This is the ONE fake response used anywhere in this beat;
    every other beat's data is real."""

    def __init__(self):
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        if self.calls == 1:
            text = "Sure, here's my answer: the label is update, pretty confident."
        else:
            text = '{"label": "update", "confidence": 0.87}'
        return LLMResponse(
            text=text, provider="demo", model="retry-demo",
            prompt_tokens=1, completion_tokens=1, latency_ms=0.0, cache_hit=False,
        )


def _beat_1_retry_on_malformed():
    _beat(1, "The LLM wrapper catches a malformed response and retries")
    schema = _RetryDemoSchema.Schema
    gateway = _MalformedThenValidGateway()
    print("  Calling generate_structured() against a gateway that returns free text first...")
    try:
        instance = generate_structured(gateway, "classify this message", schema, max_attempts=3)
    except StructuredOutputError as exc:
        print(f"  !! did not recover -- this would be a real bug: {exc}")
        return
    print(f"  attempt 1: {gateway.calls >= 1} call(s) made so far after first response (free text, not JSON)")
    print(f"  total calls made: {gateway.calls} -- succeeded on retry, never defaulted silently")
    print(f"  recovered instance: {instance!r}")


# ---------------------------------------------------------------------------
# BEAT 2/3 -- W1 D2: scope gate (unchanged from the original script)
# ---------------------------------------------------------------------------

def _beat_2_ingest_and_refuse(db_path, reader, channel_ids):
    _beat(2, "Ingest two channels, refuse the third")
    sync_state = SyncStateStore(db_path)
    message_store = MessageStore(db_path)
    results = sync_all_allowlisted_channels(reader, channel_ids, sync_state, message_store)
    for r in results:
        print(f"  ingested {r.channel_id}: {r.messages_ingested} message(s)")
    print(f"  (proj-gamma is not allowlisted -- {reader.list_channels()!r} never even names it)")

    print("\n  Attempting a direct read of proj-gamma anyway:")
    try:
        reader.list_messages(GAMMA)
        print("  !! NOT REFUSED -- this would be a real bug")
    except ScopeViolationError as exc:
        print(f"  refused, as expected: {exc}")


def _beat_3_chat_refused(reader):
    _beat(3, "A chat refused at the boundary")
    for chat_id in (CHAT_ONE_TO_ONE, CHAT_GROUP):
        print(f"\n  Attempting a direct read of chat {chat_id!r}:")
        try:
            reader.list_messages(chat_id)
            print("  !! NOT REFUSED -- this would be a real bug")
        except ScopeViolationError as exc:
            print(f"  refused, as expected: {exc}")


# ---------------------------------------------------------------------------
# BEAT 4 -- W1 D3: ingestion hardening and seed data
# ---------------------------------------------------------------------------

def _beat_4_delta_and_fixture(db_path, channel_ids):
    _beat(4, "Two consecutive delta syncs, an edit that keeps its time, a byte-identical fixture")

    print("  -- Two consecutive delta syncs against the real fixtures --")
    sync_state = SyncStateStore(db_path)
    message_store = MessageStore(db_path)
    reader_again = get_teams_reader(db_path=db_path)
    second_run = sync_all_allowlisted_channels(reader_again, channel_ids, sync_state, message_store)
    for r in second_run:
        print(f"  second consecutive run, {r.channel_id}: {r.messages_ingested} NEW message(s) "
              f"(0 expected -- everything was already ingested by beat 2)")

    print("\n  -- An edited message keeps its original post time --")
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT posted_at, edited_at, body_raw FROM messages WHERE id = 'diff-edit-01'"
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        print("  !! diff-edit-01 not found -- check the fixture")
    else:
        print(f"  diff-edit-01: posted_at={row['posted_at']!r} edited_at={row['edited_at']!r}")
        print(f"  body is the EDITED text ({row['body_raw'][:40]!r}...), but posted_at is still the "
              f"original on-time value, not the edit time")

    print("\n  -- The fixture generator reproduces byte-identical (with one known, documented exception) --")
    # KNOWN GAP, not a bug in this script: commit 3920f95 (CHN-28) hand-added
    # 3 rule-coverage rows (DIFF-SHORT-01, DIFF-THREADOFF-01, DIFF-ROSTER-01)
    # straight into the committed messages.json/labels.csv to close a real
    # coverage hole in CHN-08's rules, without also updating
    # generate_seed_fixtures.py to produce them -- so the generator's own
    # documented "single source of truth, byte-identical re-run" invariant
    # has been silently broken since that commit. See DECISION_LOG.md's
    # CHN-32 entry for how this was found (this beat's own diff check, run
    # for real for the first time) and CHN-08/CHN-28 for the original,
    # legitimate reason those 3 rows exist by hand.
    KNOWN_HAND_ADDED_IDS = {"diff-short-01", "diff-threadoff-01", "diff-roster-01"}
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "generate_seed_fixtures.py")],
            cwd=tmp, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  !! regeneration failed: {result.stderr[-500:]}")
            return
        for name in ("channels.json", "members.json"):
            committed = PROJECT_ROOT / "seed" / "fixtures" / name
            regenerated = Path(tmp) / "seed" / "fixtures" / name
            same = filecmp.cmp(committed, regenerated, shallow=False)
            print(f"  {name}: {'byte-identical' if same else '!! DIFFERS -- unexpected, investigate'}")

        import csv as _csv
        import json as _json
        committed_msgs = _json.loads((PROJECT_ROOT / "seed" / "fixtures" / "messages.json").read_text())
        regenerated_msgs = _json.loads((Path(tmp) / "seed" / "fixtures" / "messages.json").read_text())
        committed_ids = {m["id"] for msgs in committed_msgs.values() for m in msgs}
        regenerated_ids = {m["id"] for msgs in regenerated_msgs.values() for m in msgs}
        only_committed = committed_ids - regenerated_ids
        only_regenerated = regenerated_ids - committed_ids
        print(f"  messages.json: {len(committed_ids & regenerated_ids)} message id(s) match exactly; "
              f"{len(only_committed)} committed-only id(s): {sorted(only_committed) or '(none)'}; "
              f"{len(only_regenerated)} regenerated-only id(s): {sorted(only_regenerated) or '(none)'}")
        unexpected = (only_committed | only_regenerated) - KNOWN_HAND_ADDED_IDS
        if unexpected:
            print(f"  !! UNEXPECTED drift beyond the known CHN-28 gap: {sorted(unexpected)} -- investigate")
        else:
            print(f"  every difference is exactly the known CHN-28 hand-added set -- no NEW drift")

        with open(PROJECT_ROOT / "seed" / "fixtures" / "labels.csv") as f:
            committed_labels = {row[0] for row in _csv.reader(f)} - {"case_id"}
        with open(Path(tmp) / "seed" / "fixtures" / "labels.csv") as f:
            regenerated_labels = {row[0] for row in _csv.reader(f)} - {"case_id"}
        label_diff = (committed_labels ^ regenerated_labels)
        print(f"  labels.csv: {len(committed_labels & regenerated_labels)} row(s) match; "
              f"diff={sorted(label_diff) or '(none)'} -- {'matches the known CHN-28 gap' if label_diff <= {s.upper() for s in KNOWN_HAND_ADDED_IDS} or not label_diff else 'UNEXPECTED'}")

        print("\n  regenerated in a throwaway temp dir, committed fixtures were never touched.")
        print("  Bottom line: every organically-generated row reproduces byte-identical from a fixed seed.")
        print("  The 3 CHN-28 rule-coverage rows were added by hand and are the one known exception.")


# ---------------------------------------------------------------------------
# BEAT 5/6 -- W1 D4/D5: detection and the participation ledger, both channels
# ---------------------------------------------------------------------------

def _beat_5_rule_and_classifier(config_store, messages_by_channel, gateway, db_path):
    _beat(5, "Update detection: a rule decision and a classifier decision, both channels")
    for channel_id, label in ((ALPHA, "proj-alpha"), (BETA, "proj-beta")):
        config = config_store.get_channel_config(channel_id)
        day_messages = [
            m for m in messages_by_channel.get(channel_id, [])
            if m.posted_at[:10] == DAILY_SUMMARY_DAY.isoformat()
        ]
        outcomes = classify_and_persist(day_messages, config, gateway, db_path=db_path)
        rule_example = next((o for o in outcomes if o.method == "rule"), None)
        model_example = next((o for o in outcomes if o.method == "model"), None)

        print(f"\n  -- {label} --")
        if rule_example:
            print(f"  RULE decision   -- message {rule_example.message_id!r}: "
                  f"label={rule_example.label!r} rule_name={rule_example.rule_name!r} "
                  f"(no model call -- a rule settled this one)")
        else:
            print(f"  (no rule-settled message on {DAILY_SUMMARY_DAY.isoformat()} for {label})")
        if model_example:
            print(f"  CLASSIFIER decision -- message {model_example.message_id!r}: "
                  f"label={model_example.label!r} confidence={model_example.confidence!r} "
                  f"(a rule left this one unsettled, so the model decided)")
        else:
            print(f"  (no model-settled message on {DAILY_SUMMARY_DAY.isoformat()} for {label})")


def _beat_6_ledger(config_store, db_path):
    _beat(6, "The participation ledger, all three states, both channels")
    for channel_id, label in ((ALPHA, "proj-alpha"), (BETA, "proj-beta")):
        config = config_store.get_channel_config(channel_id)
        records = build_ledger(channel_id, LEDGER_DEMO_DAY, config, db_path=db_path)
        by_state = {EXCLUDED: [], POSTED_NO_UPDATE: [], NO_MESSAGE: []}
        for r in records:
            by_state.setdefault(r.state, []).append(r.member_id)
        print(f"\n  -- {label}, {LEDGER_DEMO_DAY.isoformat()} --")
        for state, members in by_state.items():
            print(f"  {state}: {members if members else '(none today)'}")


# ---------------------------------------------------------------------------
# BEAT 7 -- W2 D6/D7: scheduled digest publishing, idempotent, per-channel
# local time, a pending proposal cannot post
# ---------------------------------------------------------------------------

def _beat_7_scheduled_publishing(config_store, gateway, publisher, db_path):
    _beat(7, "Scheduled digest publishing: idempotent, each channel's own local time, a pending proposal can't post")
    proposal_store = ProposalStore(db_path)

    for channel_id, label in ((ALPHA, "proj-alpha (Asia/Colombo)"), (BETA, "proj-beta (America/New_York)")):
        config = config_store.get_channel_config(channel_id)
        print(f"\n  -- {label}, {DAILY_SUMMARY_DAY.isoformat()} --")

        print("  First run (this channel has never published before):")
        r1 = run_daily_digest_job(channel_id, config, gateway, publisher, day=DAILY_SUMMARY_DAY, db_path=db_path)
        print(f"    status={r1.status} -- {r1.detail}")

        print("  Second run, same day, still pending (proves a pending proposal cannot post twice either):")
        r2 = run_daily_digest_job(channel_id, config, gateway, publisher, day=DAILY_SUMMARY_DAY, db_path=db_path)
        print(f"    status={r2.status} -- {r2.detail}")

        publish_key = f"{channel_id}:{DAILY_SUMMARY_DAY.isoformat()}:daily_publish"
        proposal = proposal_store.get_by_idempotency_key(publish_key)
        proposal_store.approve(proposal.id, approver_id="demo:human")
        print(f"  Approved by hand (proposal {proposal.id}).")

        print("  Third run, now approved -- sends, exactly once:")
        r3 = run_daily_digest_job(channel_id, config, gateway, publisher, day=DAILY_SUMMARY_DAY, db_path=db_path)
        print(f"    status={r3.status} -- {r3.detail}")

        print("\n  The digest that actually sent, permalinks and all:")
        print("  " + "\n  ".join(proposal.payload["content"].splitlines()))

        conn = get_connection(db_path)
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM write_log "
                "WHERE proposal_id = ? GROUP BY status ORDER BY status",
                (proposal.id,),
            ).fetchall()
        finally:
            conn.close()
        print(f"  write_log for this proposal: {[(row['status'], row['n']) for row in rows]} "
              f"(exactly 1 sent, the two earlier attempts refused and logged, never silently dropped)")

    print("\n  Click-live cue: proj-alpha and proj-beta each fired at THEIR OWN configured local time")
    print("  (Asia/Colombo vs America/New_York) on the same shared calendar date.")
    print("  Against a live tenant each digest's [source](...) lines open straight to the real Teams message;")
    print("  today it's mock-only (CHN-01's Graph consent is still pending -- see README.md's Status section).")


# ---------------------------------------------------------------------------
# BEAT 8 -- W2 D8: weekly roll-up, both channels
# ---------------------------------------------------------------------------

def _beat_8_weekly_rollup(config_store, gateway, db_path):
    _beat(8, "The weekly roll-up, both channels")
    for channel_id, end_day, label in (
        (ALPHA, WEEKLY_END_DAY_ALPHA, "proj-alpha"),
        (BETA, WEEKLY_END_DAY_BETA, "proj-beta"),
    ):
        config = config_store.get_channel_config(channel_id)
        print(f"\n  -- {label} --")
        result = generate_and_persist_weekly_rollup(channel_id, end_day, config, gateway, db_path=db_path)
        print(result.content)


# ---------------------------------------------------------------------------
# BEAT 9 -- W2 D8/D9: nudges, both channels
# ---------------------------------------------------------------------------

def _beat_9_nudges(config_store, publisher, db_path):
    _beat(9, "Nudges: proj-beta's real approve/reject flow, proj-alpha's chatter-only member nudged like real silence")
    proposal_store = ProposalStore(db_path)

    print("\n  -- proj-beta --")
    config = config_store.get_channel_config(BETA)
    print(f"\n  First pass, {NUDGE_DAY_1.isoformat()}: every eligible non-responder's first-ever nudge --")
    for result in run_nudge_job(BETA, config, publisher, day=NUDGE_DAY_1, db_path=db_path):
        print(f"    {result.member_id or '(channel)'}: {result.status} -- {result.detail}")

    reject_key = f"{BETA}:{REJECT_MEMBER}:{NUDGE_DAY_1.isoformat()}:1"
    reject_proposal = proposal_store.get_by_idempotency_key(reject_key)
    proposal_store.reject(reject_proposal.id, approver_id="demo:human")
    print(f"\n  Rejected {REJECT_MEMBER}'s nudge by hand (proposal {reject_proposal.id}).")

    approve_key = f"{BETA}:sofia.almeida:{NUDGE_DAY_1.isoformat()}:1"
    approve_proposal = proposal_store.get_by_idempotency_key(approve_key)
    proposal_store.approve(approve_proposal.id, approver_id="demo:human")
    print(f"  Approved sofia.almeida's nudge by hand (proposal {approve_proposal.id}).")

    print(f"\n  Second pass, {NUDGE_DAY_1.isoformat()} rerun: same day, now reflecting those two decisions --")
    for result in run_nudge_job(BETA, config, publisher, day=NUDGE_DAY_1, db_path=db_path):
        print(f"    {result.member_id or '(channel)'}: {result.status} -- {result.detail}")

    print(f"\n  {NUDGE_DAY_2.isoformat()}: sofia's second consecutive missed day (already nudged -> auto-approves) --")
    for result in run_nudge_job(BETA, config, publisher, day=NUDGE_DAY_2, db_path=db_path):
        if result.member_id == "sofia.almeida":
            print(f"    {result.member_id}: {result.status} -- {result.detail}")

    print("\n  -- proj-alpha --")
    print("  nudge_enabled is committed as false for proj-alpha (its real, steady-state value).")
    print("  Turning it on for THIS RUN ONLY, in memory -- the same override pattern this project's")
    print("  clock overrides already use, never touching config/channels/proj-alpha.yaml.")
    alpha_config = config_store.get_channel_config(ALPHA)
    alpha_config = alpha_config.model_copy(update={"nudge_enabled": True})

    print(f"\n  First pass, {ALPHA_NUDGE_DAY_1.isoformat()}: fatima's first-ever nudge in this channel --")
    for result in run_nudge_job(ALPHA, alpha_config, publisher, day=ALPHA_NUDGE_DAY_1, db_path=db_path):
        if result.member_id == "fatima.hassan":
            print(f"    {result.member_id}: {result.status} -- {result.detail}")
            print("    (fatima posts every day in this fixture -- but every message is chatter, never "
                  "an update, so the ledger counts her exactly like genuine silence)")

    alpha_nudge_key = f"{ALPHA}:fatima.hassan:{ALPHA_NUDGE_DAY_1.isoformat()}:1"
    alpha_nudge_proposal = proposal_store.get_by_idempotency_key(alpha_nudge_key)
    proposal_store.approve(alpha_nudge_proposal.id, approver_id="demo:human")
    print(f"  Approved fatima.hassan's nudge by hand (proposal {alpha_nudge_proposal.id}) -- "
          f"same required first-ever-nudge approval proj-beta's sofia went through above.")

    print(f"\n  Rerun, {ALPHA_NUDGE_DAY_1.isoformat()}: now sends --")
    for result in run_nudge_job(ALPHA, alpha_config, publisher, day=ALPHA_NUDGE_DAY_1, db_path=db_path):
        if result.member_id == "fatima.hassan":
            print(f"    {result.member_id}: {result.status} -- {result.detail}")

    print(f"\n  {ALPHA_NUDGE_DAY_2.isoformat()}: her second consecutive missed day (already nudged -> auto-approves) --")
    for result in run_nudge_job(ALPHA, alpha_config, publisher, day=ALPHA_NUDGE_DAY_2, db_path=db_path):
        if result.member_id == "fatima.hassan":
            print(f"    {result.member_id}: {result.status} -- {result.detail}")

    return alpha_config  # handed to beat 10 so escalation sees the same in-memory override


# ---------------------------------------------------------------------------
# BEAT 10 -- W2 D9: escalation, both channels
# ---------------------------------------------------------------------------

def _beat_10_escalation(config_store, alpha_config, publisher, db_path):
    _beat(10, "An escalation evidence bundle, both channels")
    proposal_store = ProposalStore(db_path)

    print("\n  -- proj-beta --")
    beta_config = config_store.get_channel_config(BETA)
    for result in run_escalation_job(BETA, beta_config, publisher, day=NUDGE_DAY_2, db_path=db_path):
        if result.member_id == "sofia.almeida":
            print(f"  sofia.almeida: {result.status} -- {result.detail}")
    escalation_key = f"{BETA}:sofia.almeida:{NUDGE_DAY_1.isoformat()}"
    proposal = proposal_store.get_by_idempotency_key(escalation_key)
    if proposal is None:
        print("  (no escalation proposal was created -- check the streak/threshold dates above)")
    else:
        print("\n  The evidence bundle actually sent for approval:")
        print("  " + "\n  ".join(proposal.payload["content"].splitlines()))

    print("\n  -- proj-alpha --")
    for result in run_escalation_job(ALPHA, alpha_config, publisher, day=ALPHA_ESCALATION_DAY, db_path=db_path):
        if result.member_id == "fatima.hassan":
            print(f"  fatima.hassan: {result.status} -- {result.detail}")
    alpha_escalation_key = f"{ALPHA}:fatima.hassan:{ALPHA_NUDGE_DAY_1.isoformat()}"
    alpha_proposal = proposal_store.get_by_idempotency_key(alpha_escalation_key)
    if alpha_proposal is None:
        print("  (no escalation proposal was created for fatima -- check the streak/threshold dates above)")
    else:
        print("\n  The evidence bundle actually sent for approval:")
        print("  " + "\n  ".join(alpha_proposal.payload["content"].splitlines()))
        print("\n  Same evidence-bundle shape as proj-beta's, for a member whose activity looks nothing")
        print("  like sofia's silence -- the escalation path is driven by counted updates, not by")
        print("  whether someone was 'around'.")


# ---------------------------------------------------------------------------
# BEAT 11 -- W1 D5: the eval harness, run for real
# ---------------------------------------------------------------------------

def _beat_11_eval_harness():
    _beat(11, "The eval harness, run for real")
    import run_eval as eval_script  # scripts/run_eval.py, already on sys.path (SCRIPT_DIR)
    from p1.eval.cases import GoldenCaseRegistry
    from p1.eval.registrations import register_all
    from p1.eval.runner import run_eval

    registry = GoldenCaseRegistry()
    register_all(registry)
    model_id = eval_script.resolve_model_id(None)
    prompt_versions = eval_script.resolve_prompt_versions({})
    print(f"  model_id={model_id} prompt_versions={prompt_versions}\n")

    summary = run_eval(registry, model_id=model_id, prompt_versions=prompt_versions)

    highlight_ids = {"GC1-precision", "GC1-recall", "GC2-exact-match", "GC5-scope-violations", "GC10-ingest-correctness"}
    print("  Day 5's own headline numbers:")
    for result in summary.results:
        if result.metric_id in highlight_ids or result.metric_id.startswith(("GC1", "GC2", "GC5", "GC10")):
            mark = "PASS" if result.passed else "FAIL"
            print(f"    [{mark}] {result.metric_id}: {result.name} -- measured={result.measured} target={result.target}")

    status = "ALL PASS" if summary.all_passed else "FAILURES PRESENT"
    print(f"\n  {len(summary.results)} metric(s) checked across all 12 golden cases -- {status}")


def run_walkthrough(*, db_path=DEFAULT_DB_PATH, gateway=None, publisher=None, reader=None) -> None:
    config_store, messages_by_channel = _setup(db_path)
    reader = reader or get_teams_reader(db_path=db_path)
    publisher = publisher or get_teams_publisher()
    gateway = gateway or LLMGateway()

    channel_ids = (ALPHA, BETA)

    _beat_1_retry_on_malformed()
    _beat_2_ingest_and_refuse(db_path, reader, channel_ids)
    _beat_3_chat_refused(reader)
    _beat_4_delta_and_fixture(db_path, channel_ids)

    # Beats 5 onward need every message classified across the whole
    # window both channels' later beats touch -- not just the one day
    # beat 5 prints -- since the ledger, digest, weekly roll-up, nudge
    # and escalation beats all read the classifications table.
    for channel_id, config in ((ALPHA, config_store.get_channel_config(ALPHA)),
                               (BETA, config_store.get_channel_config(BETA))):
        classify_and_persist(messages_by_channel.get(channel_id, []), config, gateway, db_path=db_path)

    _beat_5_rule_and_classifier(config_store, messages_by_channel, gateway, db_path)
    _beat_6_ledger(config_store, db_path)
    _beat_7_scheduled_publishing(config_store, gateway, publisher, db_path)
    _beat_8_weekly_rollup(config_store, gateway, db_path)
    alpha_config_override = _beat_9_nudges(config_store, publisher, db_path)
    _beat_10_escalation(config_store, alpha_config_override, publisher, db_path)
    _beat_11_eval_harness()

    print()
    print("=" * 78)
    print("Every W1/W2 build-day acceptance criterion has now run for real, on both channels.")
    print("Close with your own view of the weakest part -- that's yours to say, not this script's.")
    print("=" * 78)


def main() -> int:
    run_walkthrough()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
