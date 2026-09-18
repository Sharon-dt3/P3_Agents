"""
CHN-32: the recorded walkthrough's own real backing script.

Run this once, on camera, with a real ANTHROPIC_API_KEY in .env --
every digest/summary/weekly-narrative line the model writes is a real
call (see p1.reporting.daily_summary's own docstring, same as CHN-31's
scripts/run_daily.py). It prints one clearly marked "BEAT" section per
item CHN-32's own WBS row lists, top to bottom, in the same order the
row lists them, so the recording can just follow this script's output:

  1. Ingest two channels and refuse the third
  2. A chat refused at the boundary
  3. Update detection: a rule decision and a classifier decision
  4. The participation ledger, all three states
  5. The daily summary, with a permalink
  6. The weekly roll-up
  7. A nudge held at approval, and one rejected
  8. An escalation evidence bundle

The eval output (the WBS row's 9th beat) is deliberately NOT run from
inside this script -- it's its own existing, already-working command
(`uv run python scripts/run_eval.py`), meant to be run as its own step
during the same recording, right after this script finishes.

Everything here calls the exact same production functions every unit
test, GC, and CHN-31's scripts/run_daily.py already exercise -- ingestion
goes through the real p1.adapters.factory.get_teams_reader() and
p1.ingestion.sync.sync_all_allowlisted_channels(), the same production
wiring GC5 proves, not CHN-31's own fixture-loading shortcut. There is
no second, demo-only code path anywhere in this script.

One piece of real data worth naming up front, since it drives beats 7
and 8: proj-beta's sofia.almeida has a genuine, naturally-occurring
7-consecutive-working-day silence already sitting in the committed
fixtures (2025-06-05 through 2025-06-13) -- nothing was added or
adjusted to manufacture the nudge/escalation beats. Her real streak
clears proj-beta's own escalation_threshold_days (2) on its own, and
kenji.tanaka's real, near-total "posted, but nothing counted" pattern
across the same window is what beat 7 uses to show the OTHER nudge
wording (see p1.nudges.nudge_job._render_nudge_message). See
DECISION_LOG.md's CHN-32 entry for how these were found (a direct
build_ledger() query across the whole fixture window, not guessed at).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from p1.adapters.factory import get_teams_publisher, get_teams_reader
from p1.adapters.fixtures import load_teams_fixtures
from p1.approval.proposals import ProposalStore
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.escalations.escalation_job import run_escalation_job
from p1.governance.scope_gate import ScopeViolationError
from p1.ingestion.sync import sync_all_allowlisted_channels
from p1.llm.gateway import LLMGateway
from p1.nudges.nudge_job import run_nudge_job
from p1.participation.ledger import EXCLUDED, NO_MESSAGE, POSTED_NO_UPDATE, build_ledger
from p1.reporting.daily_summary import generate_and_persist_daily_summary
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

DAILY_SUMMARY_DAY = date(2025, 6, 6)     # proj-alpha's busiest real day (13 messages)
LEDGER_DEMO_DAY = date(2025, 6, 5)       # proj-alpha: excluded + posted_no_update + no_message, all real
WEEKLY_END_DAY = date(2025, 6, 12)       # proj-beta's own configured weekly_digest_day (Thu)
NUDGE_DAY_1 = date(2025, 6, 5)           # sofia's first real missed day on proj-beta
NUDGE_DAY_2 = date(2025, 6, 6)           # sofia's second consecutive real missed day
REJECT_MEMBER = "amara.okonkwo"          # whoever's nudge we reject on camera, for real


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


def _beat_1_ingest_and_refuse(db_path, reader, channel_ids):
    _beat(1, "Ingest two channels, refuse the third")
    sync_state = SyncStateStore(db_path)
    message_store = MessageStore(db_path)
    results = sync_all_allowlisted_channels(reader, channel_ids, sync_state, message_store)
    for r in results:
        print(f"  ingested {r.channel_id}: {r.messages_ingested} message(s)")
    # Narration only -- this mock reader's own list_channels() is a free,
    # illustrative call (never touches real Graph, needs no permission),
    # unlike production's sync_all_allowlisted_channels() above, which no
    # longer calls it at all (see DECISION_LOG.md's CHN-01 follow-up).
    print(f"  (proj-gamma is not allowlisted -- {reader.list_channels()!r} never even names it)")

    print("\n  Attempting a direct read of proj-gamma anyway:")
    try:
        reader.list_messages(GAMMA)
        print("  !! NOT REFUSED -- this would be a real bug")
    except ScopeViolationError as exc:
        print(f"  refused, as expected: {exc}")


def _beat_2_chat_refused(reader):
    _beat(2, "A chat refused at the boundary")
    for chat_id in (CHAT_ONE_TO_ONE, CHAT_GROUP):
        print(f"\n  Attempting a direct read of chat {chat_id!r}:")
        try:
            reader.list_messages(chat_id)
            print("  !! NOT REFUSED -- this would be a real bug")
        except ScopeViolationError as exc:
            print(f"  refused, as expected: {exc}")


def _beat_3_rule_and_classifier(config_store, messages_by_channel, gateway, db_path):
    _beat(3, "Update detection: a rule decision and a classifier decision")
    config = config_store.get_channel_config(ALPHA)
    day_messages = [
        m for m in messages_by_channel.get(ALPHA, [])
        if m.posted_at[:10] == DAILY_SUMMARY_DAY.isoformat()
    ]
    outcomes = classify_and_persist(day_messages, config, gateway, db_path=db_path)

    rule_example = next((o for o in outcomes if o.method == "rule"), None)
    model_example = next((o for o in outcomes if o.method == "model"), None)

    if rule_example:
        print(f"  RULE decision   -- message {rule_example.message_id!r}: "
              f"label={rule_example.label!r} rule_name={rule_example.rule_name!r} "
              f"(no model call -- a rule settled this one)")
    else:
        print(f"  (no rule-settled message on {DAILY_SUMMARY_DAY.isoformat()} -- try a different day)")

    if model_example:
        print(f"  CLASSIFIER decision -- message {model_example.message_id!r}: "
              f"label={model_example.label!r} confidence={model_example.confidence!r} "
              f"(a rule left this one unsettled, so the model decided)")
    else:
        print(f"  (no model-settled message on {DAILY_SUMMARY_DAY.isoformat()} -- try a different day)")


def _beat_4_ledger(config_store, db_path):
    _beat(4, "The participation ledger, all three states")
    config = config_store.get_channel_config(ALPHA)
    records = build_ledger(ALPHA, LEDGER_DEMO_DAY, config, db_path=db_path)
    by_state = {EXCLUDED: [], POSTED_NO_UPDATE: [], NO_MESSAGE: []}
    for r in records:
        by_state.setdefault(r.state, []).append(r.member_id)
    for state, members in by_state.items():
        print(f"  {state}: {members if members else '(none today)'}")


def _beat_5_daily_summary(config_store, gateway, db_path):
    _beat(5, "The daily summary, with a permalink")
    config = config_store.get_channel_config(ALPHA)
    result = generate_and_persist_daily_summary(ALPHA, DAILY_SUMMARY_DAY, config, gateway, db_path=db_path)
    print(result.content)
    permalink_lines = [ln for ln in result.content.splitlines() if "https://teams.microsoft.com" in ln]
    if permalink_lines:
        print("\n  >>> Click-live cue: the permalink in this line --")
        print(f"      {permalink_lines[0].strip()}")
        print("  >>> is well-formed and traces to a real message in our own store. Against a live")
        print("  >>> tenant it opens straight to that Teams message; today it's mock-only (CHN-01's")
        print("  >>> Graph consent is still pending -- see README.md's Status section), so say that")
        print("  >>> on camera rather than clicking through to nothing.")


def _beat_6_weekly_rollup(config_store, gateway, db_path):
    _beat(6, "The weekly roll-up")
    config = config_store.get_channel_config(BETA)
    result = generate_and_persist_weekly_rollup(BETA, WEEKLY_END_DAY, config, gateway, db_path=db_path)
    print(result.content)


def _beat_7_nudge_held_and_rejected(config_store, publisher, db_path):
    _beat(7, "A nudge held at approval, and one rejected")
    config = config_store.get_channel_config(BETA)
    proposal_store = ProposalStore(db_path)

    print(f"\n  -- First pass, {NUDGE_DAY_1.isoformat()}: every eligible non-responder's first-ever nudge --")
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

    print(f"\n  -- Second pass, {NUDGE_DAY_1.isoformat()} rerun: same day, now reflecting those two decisions --")
    for result in run_nudge_job(BETA, config, publisher, day=NUDGE_DAY_1, db_path=db_path):
        print(f"    {result.member_id or '(channel)'}: {result.status} -- {result.detail}")

    print(f"\n  -- {NUDGE_DAY_2.isoformat()}: sofia's second consecutive missed day (already nudged -> auto-approves) --")
    for result in run_nudge_job(BETA, config, publisher, day=NUDGE_DAY_2, db_path=db_path):
        if result.member_id == "sofia.almeida":
            print(f"    {result.member_id}: {result.status} -- {result.detail}")


def _beat_8_escalation(config_store, publisher, db_path):
    _beat(8, "An escalation evidence bundle")
    config = config_store.get_channel_config(BETA)
    proposal_store = ProposalStore(db_path)

    for result in run_escalation_job(BETA, config, publisher, day=NUDGE_DAY_2, db_path=db_path):
        if result.member_id == "sofia.almeida":
            print(f"  sofia.almeida: {result.status} -- {result.detail}")

    escalation_key = f"{BETA}:sofia.almeida:{NUDGE_DAY_1.isoformat()}"
    proposal = proposal_store.get_by_idempotency_key(escalation_key)
    if proposal is None:
        print("  (no escalation proposal was created -- check the streak/threshold dates above)")
        return
    print("\n  The evidence bundle actually sent for approval:")
    print("  " + "\n  ".join(proposal.payload["content"].splitlines()))


def run_walkthrough(*, db_path=DEFAULT_DB_PATH, gateway=None, publisher=None, reader=None) -> None:
    config_store, messages_by_channel = _setup(db_path)
    reader = reader or get_teams_reader(db_path=db_path)
    publisher = publisher or get_teams_publisher()
    gateway = gateway or LLMGateway()

    channel_ids = (ALPHA, BETA)
    _beat_1_ingest_and_refuse(db_path, reader, channel_ids)
    _beat_2_chat_refused(reader)

    # Beats 3 onward need every message classified across the whole
    # window both channels' later beats touch -- not just the one day
    # beat 3 prints -- since the ledger, digest, weekly roll-up, nudge
    # and escalation beats all read the classifications table.
    for channel_id, config in ((ALPHA, config_store.get_channel_config(ALPHA)),
                               (BETA, config_store.get_channel_config(BETA))):
        classify_and_persist(messages_by_channel.get(channel_id, []), config, gateway, db_path=db_path)

    _beat_3_rule_and_classifier(config_store, messages_by_channel, gateway, db_path)
    _beat_4_ledger(config_store, db_path)
    _beat_5_daily_summary(config_store, gateway, db_path)
    _beat_6_weekly_rollup(config_store, gateway, db_path)
    _beat_7_nudge_held_and_rejected(config_store, publisher, db_path)
    _beat_8_escalation(config_store, publisher, db_path)

    print()
    print("=" * 78)
    print("Next: run `uv run python scripts/run_eval.py` as its own step for the eval-output beat.")
    print("Then close with your own view of the weakest part -- that's yours to say, not this script's.")
    print("=" * 78)


def main() -> int:
    run_walkthrough()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
