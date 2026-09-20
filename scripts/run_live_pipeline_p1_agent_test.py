"""
The real, live, end-to-end run against the real p1-agent-test Teams
channel: ingest -> classify (CHN-08/09) -> build the participation
ledger and generate a digest (CHN-10/13) -> attempt to publish it
through the real Power Automate flow (CHN-22) -- via the exact same
production functions (sync_channel, classify_and_persist,
run_daily_digest_job) every mock-fixture test, GC6, and
scripts/run_daily.py already exercise. This script is what "make it
useful" means for the real pilot channel: not a second, separately
maintained live path, just those same functions pointed at the real
channel_id and a real LLMGateway/PowerAutomateTeamsPublisher instead of
fixtures and a mock.

Builds on two things this session already proved live on their own:
scripts/run_live_ingest_p1_agent_test.py (the read side) and
scripts/power_automate_smoke_test.py (the write side, called directly
rather than through this job's own approval-gated publish path). This
script is the first thing to exercise classification, the
participation ledger, and digest generation against real data at all
-- CHN-08/09/10/13 have only ever run against mock fixtures until now.

Unlike scripts/run_daily.py, this never pre-seeds a `members` row from
fixture data: p1.storage.messages_repo.MessageStore._ensure_member_exists
already inserts a member row for any real author_id ingestion
encounters, for exactly this reason (see that function's own
docstring and DECISION_LOG.md's CHN-31 entry) -- nothing here needs to
duplicate that.

Two real things worth knowing before running this for real, found
while building it, not assumed:

1. `config/channels/p1-agent-test.yaml` sets `ignore_bots: true`, and
   detection.rules.evaluate_message excludes any is_bot message via a
   rule before it ever reaches the model. The one real message in this
   channel as of this writing (scripts/power_automate_smoke_test.py's
   own test post) is bot-authored, so it will be classified as noise
   and contribute nothing to a digest -- this script will not look
   "useful" until a real, human-authored message exists in the real
   Teams channel. That is not this script's bug to fix; it requires a
   person actually posting in Teams.

2. The channel's own `working_days` is Mon-Fri; run_daily_digest_job
   returns SKIPPED_NON_WORKING_DAY outright for any other day in the
   channel's own timezone (Asia/Colombo), `day` defaulting to "today"
   in that timezone. Pass --day explicitly (YYYY-MM-DD) to target a
   specific past working day's messages instead of waiting for one.

3. p1.publishing.daily_job.run_daily_digest_job requires human
   approval before its very first publish for any channel ever
   (DigestStore.has_ever_published() is False for p1-agent-test) --
   so the first real run of this script is expected to end with
   status="awaiting_approval", not an actual post. That is the
   designed behaviour ("no channel ever receives an unexpected bot
   post"), not a failure; approving it is a separate, deliberate step
   (see p1.approval.proposals.ProposalStore.approve / the approval
   dashboard).

Usage:
    uv run python scripts/run_live_pipeline_p1_agent_test.py [--day YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.factory import get_teams_publisher
from p1.adapters.teams_reader import TeamsMessage
from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.governance.scope_gate import ScopedTeamsReader
from p1.ingestion.sync import sync_channel
from p1.llm.gateway import LLMGateway
from p1.participation.ledger import build_and_persist_ledger
from p1.publishing.daily_job import JobResult, run_daily_digest_job
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

# The dedicated live database run_live_ingest_p1_agent_test.py already
# established, so a real person's real Teams content never lands in
# data/p1.db, the shared store every mock-fixture demo/eval script
# reads and writes.
LIVE_DB_PATH = "data/p1_live.db"

# config/channels/p1-agent-test.yaml's real channel_id -- the same one
# every other live script this session wrote already uses.
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"


def build_scoped_reader(
    *, access_token: str, team_id: str, db_path: str, reader_factory=GraphTeamsReader,
) -> ScopedTeamsReader:
    """Identical role to run_live_ingest_p1_agent_test.py's own helper
    of the same name -- pulled out so a test can call it directly and
    prove the real object this script builds refuses an out-of-scope
    channel_id, rather than a second, hand-rolled ScopedTeamsReader
    that would pass even if this function stopped scope-gating."""
    raw_reader = reader_factory(access_token=access_token, team_id=team_id)
    return ScopedTeamsReader(raw_reader, allowlisted_channel_ids=[CHANNEL_ID], db_path=db_path)


def _load_channel_messages(db_path: str, channel_id: str) -> list[TeamsMessage]:
    """Reconstructs TeamsMessage objects from every non-deleted row this
    channel currently has in `messages` -- classify_and_persist takes a
    list[TeamsMessage], and sync_channel() only ever returns a count,
    never the messages themselves, so this is the one read-back step a
    live run needs that a fixture-driven run (which already holds its
    TeamsMessage objects in memory) does not."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, channel_id, author_id, thread_root_id, posted_at,
                   edited_at, deleted_at, is_deleted, is_bot, is_system,
                   body_raw, permalink
            FROM messages
            WHERE channel_id = ? AND is_deleted = 0
            """,
            (channel_id,),
        ).fetchall()
    finally:
        conn.close()

    return [
        TeamsMessage(
            id=row["id"],
            channel_id=row["channel_id"],
            author_id=row["author_id"],
            thread_root_id=row["thread_root_id"],
            posted_at=row["posted_at"],
            edited_at=row["edited_at"],
            deleted_at=row["deleted_at"],
            is_deleted=bool(row["is_deleted"]),
            is_bot=bool(row["is_bot"]),
            is_system=bool(row["is_system"]),
            body=row["body_raw"] or "",
            permalink=row["permalink"],
        )
        for row in rows
    ]


def run_live_pipeline(
    *,
    access_token: str,
    team_id: str,
    day: date | None = None,
    db_path: str = LIVE_DB_PATH,
    reader_factory=GraphTeamsReader,
    gateway=None,
    publisher=None,
) -> JobResult:
    """reader_factory/gateway/publisher are seams for tests: production
    always builds the real GraphTeamsReader, LLMGateway, and whatever
    get_teams_publisher() resolves to from TEAMS_PUBLISHER_MODE (all
    three defaults), tests substitute fakes that never touch a real
    network, model, or Teams tenant."""
    init_db(db_path)
    # sync_state.channel_id and messages.author_id are both foreign
    # keys (channels.id, members.id respectively) -- sync_to_db()
    # registers every configured channel; author rows are handled
    # per-message by MessageStore itself (see this module's docstring).
    ChannelConfigStore().sync_to_db(db_path)

    reader = build_scoped_reader(
        access_token=access_token, team_id=team_id, db_path=db_path, reader_factory=reader_factory,
    )
    sync_state = SyncStateStore(db_path)
    message_store = MessageStore(db_path)
    sync_result = sync_channel(reader, CHANNEL_ID, sync_state, message_store)
    resynced_note = " (resynced from scratch -- prior delta token had expired)" if sync_result.resynced else ""
    print(f"Ingested {sync_result.messages_ingested} new message(s) from {CHANNEL_ID}{resynced_note}.")

    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    messages = _load_channel_messages(db_path, CHANNEL_ID)
    print(f"{len(messages)} total non-deleted message(s) known for this channel in {db_path}.")

    gateway = gateway or LLMGateway()
    publisher = publisher or get_teams_publisher()

    outcomes = classify_and_persist(messages, config, gateway, db_path=db_path)
    noise_count = sum(1 for o in outcomes if o.label == "noise")
    signal_count = len(outcomes) - noise_count
    print(f"Classified {len(outcomes)} message(s): {signal_count} signal, {noise_count} noise.")

    result = run_daily_digest_job(CHANNEL_ID, config, gateway, publisher, day=day, db_path=db_path)
    print(f"[run] {config.display_name} ({CHANNEL_ID}) {result.date}: {result.status} -- {result.detail}")

    # Visibility only, not part of the scored production path: every real
    # caller (daily_summary, nudge_job, escalation_job) deliberately reads
    # the ledger fresh via build_ledger() rather than a persisted table, so
    # a digest never reports a stale ledger (see daily_summary.py's own
    # docstring). This script additionally persists the same day's ledger
    # so the real participation table has a human-visible row to look at
    # (e.g. via sqlite_web or the Supabase mirror) -- the digest and every
    # downstream job's own behaviour never depend on this call or its
    # result.
    ledger_records = build_and_persist_ledger(CHANNEL_ID, date.fromisoformat(result.date), config, db_path=db_path)
    print(f"Persisted {len(ledger_records)} participation ledger row(s) for {result.date} "
          "(only non-responders are ever recorded -- see p1.participation.ledger's own docstring).")

    return result


def _parse_day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--day",
        default=None,
        help="Target a specific working day (YYYY-MM-DD) instead of today in the channel's own timezone.",
    )
    args = parser.parse_args()

    access_token = os.environ.get("GRAPH_ACCESS_TOKEN")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not access_token or not team_id:
        print("GRAPH_ACCESS_TOKEN and GRAPH_TEAM_ID must both be set in .env -- run scripts/graph_login.py first.")
        return 1

    result = run_live_pipeline(access_token=access_token, team_id=team_id, day=_parse_day(args.day))
    return 0 if result.status != "rejected" else 1


if __name__ == "__main__":
    raise SystemExit(main())
