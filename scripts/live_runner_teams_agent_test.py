"""
The live, always-on process for p1-agent-test: the piece that was
missing from every other script in this directory. Every ingest,
digest, nudge, and escalation run against this channel so far has been
a person manually invoking a one-off script -- there has never been a
single running process that keeps this channel's pipeline moving on
its own. This script is that process. It does not exit on its own;
leave it running in a terminal (or under a real process supervisor for
actual production use -- not attempted here, see DECISION_LOG.md).

Three independent things run on their own schedule, in one process:

  1. Ingestion polling (NEW -- nothing before this called sync_channel()
     on any kind of schedule; every prior real run was triggered by a
     person). Every INGEST_POLL_MINUTES (default 5), this fetches a
     fresh Graph access token via p1.adapters.graph_auth's silent
     refresh and calls sync_channel() -- exactly the same call
     run_live_pipeline_p1_agent_test.py already makes by hand, just on
     a timer instead of a keypress. This is what makes a message posted
     mid-morning actually visible to a same-day digest or nudge, instead
     of only ever being as fresh as the last time someone happened to
     run a script.

  2. The daily digest job, via p1.publishing.scheduler.build_scheduler()
     -- a real APScheduler CronTrigger firing run_daily_digest_job at
     this channel's own configured daily_digest_time. That function
     already existed and was already tested; nothing before this script
     ever called .start() on the scheduler it returns. This script is
     the first thing that does.

  3. Nudges, then escalation (NEW -- build_scheduler() only ever covered
     the daily digest; nudge_job.py and escalation_job.py have never
     been wired into any scheduler at all, only ever run by hand). Fires
     once per configured working day at this channel's own
     update_window_end -- the natural "have they said anything by the
     end of today's window" moment -- running run_nudge_job() first and
     run_escalation_job() immediately after in the same tick, since
     escalation's own streak logic already requires nudging to have
     happened first (see escalation_job.py's own guarantee 3).

Graph access tokens are short-lived (~1hr); see graph_auth.py's own
docstring for why every ingest poll here calls get_access_token with
allow_interactive=False and simply skips (logging loudly) rather than
blocking a background thread on a sign-in prompt if silent refresh
ever fails -- run scripts/graph_seed_token_cache.py again to recover.

Config (daily_digest_time, update_window_end, working_days, etc.) is
read once at startup from the committed YAML, synced to the live db the
same way every other live script here does. A config edit made while
this process is already running is NOT picked up -- restart it, the
same caveat DECISION_LOG.md already notes for the Streamlit dashboard.

Usage:
    uv run python scripts/graph_seed_token_cache.py   # once, first time only
    uv run python scripts/live_runner_p1_agent_test.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from p1.adapters.factory import get_teams_publisher
from p1.adapters.graph_auth import GraphAuthError, get_access_token
from p1.adapters.teams_reader import TeamsMessage
from p1.adapters.teams_reader_graph import GraphTeamsReader
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.escalations.escalation_job import run_escalation_job
from p1.governance.scope_gate import ScopedTeamsReader
from p1.ingestion.sync import sync_channel
from p1.llm.gateway import LLMGateway
from p1.nudges.nudge_job import run_nudge_job
from p1.publishing.scheduler import build_scheduler
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2"  # Teams-agent-test -- second channel, for the SPN-04 multi-channel isolation test (see chat/DECISION_LOG.md 2026-09-20)

INGEST_POLL_MINUTES = int(os.environ.get("INGEST_POLL_MINUTES", "5"))

_DAY_NAMES = {
    "Mon": "mon", "Tue": "tue", "Wed": "wed", "Thu": "thu",
    "Fri": "fri", "Sat": "sat", "Sun": "sun",
}


def _log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [Teams-agent-test] {msg}", flush=True)


def _load_channel_messages(db_path: str, channel_id: str) -> list[TeamsMessage]:
    """Reconstructs TeamsMessage objects from every non-deleted row this
    channel currently has in `messages` -- classify_and_persist() takes a
    list[TeamsMessage], and sync_channel() only ever returns a count, not
    the messages themselves. Same read-back this exact gap needed in
    run_live_pipeline_p1_agent_test.py's own _load_channel_messages()."""
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


def _poll_ingest(*, tenant_id: str, client_id: str, team_id: str, gateway, db_path: str) -> None:
    """One ingestion tick. Never raises -- a failed poll (expired
    refresh token, a transient Graph error, a rate limit) is logged and
    skipped; the next scheduled tick tries again on its own. Nothing
    about this function ever blocks waiting for a human.

    2026-09-20 finding: an earlier version of this function only called
    sync_channel() -- a message would land in `messages` but never in
    `classifications`, so it stayed permanently invisible to
    gather_daily_facts() (which reads classifications, never messages,
    directly) no matter how fresh ingestion was. classify_and_persist()
    is idempotent (ClassificationStore.record() is an upsert keyed on
    message_id -- see its own docstring), so reclassifying the channel's
    full known message set on every tick, not just what this tick's
    sync_channel() call happened to return, is safe and simple, matching
    run_live_pipeline_p1_agent_test.py's own approach.

    2026-09-20 second finding: this function used to receive `config`
    as a frozen argument, captured once in main() at process startup
    and never refreshed -- so a channel owner's live roster/window/
    exceptions edit (via Copilot Studio or the Streamlit dashboard,
    both of which call ChannelConfigStore.update_channel_config()) had
    no path to ever reaching this function, running or restarted (see
    DECISION_LOG.md). Config is now fetched fresh, via
    get_effective_config(), on every tick instead -- the same live-read
    path the escalation-resend flow already relied on for
    channel_owner_id."""
    try:
        access_token = get_access_token(
            tenant_id=tenant_id, client_id=client_id, allow_interactive=False,
        )
    except GraphAuthError as exc:
        _log(f"[ingest] SKIPPED -- {exc}")
        return

    try:
        config = ChannelConfigStore().get_effective_config(CHANNEL_ID, db_path=db_path)
        raw_reader = GraphTeamsReader(access_token=access_token, team_id=team_id)
        reader = ScopedTeamsReader(raw_reader, allowlisted_channel_ids=[CHANNEL_ID], db_path=db_path)
        sync_state = SyncStateStore(db_path)
        message_store = MessageStore(db_path)
        result = sync_channel(reader, CHANNEL_ID, sync_state, message_store)
        note = " (resynced from scratch)" if result.resynced else ""
        _log(f"[ingest] {result.messages_ingested} new message(s){note}")

        messages = _load_channel_messages(db_path, CHANNEL_ID)
        outcomes = classify_and_persist(messages, config, gateway, db_path=db_path)
        noise_count = sum(1 for o in outcomes if o.label == "noise")
        _log(f"[classify] {len(outcomes)} message(s) evaluated: {len(outcomes) - noise_count} signal, {noise_count} noise")
    except Exception as exc:  # noqa: BLE001 -- a poll tick must never crash the scheduler thread
        _log(f"[ingest] FAILED -- {type(exc).__name__}: {exc}")


def _run_nudges_and_escalations(*, publisher, db_path: str) -> None:
    """One end-of-window tick: nudges first, escalation immediately
    after, matching escalation_job.py's own hard requirement that a
    person must already have been nudged before they can ever be
    escalated. Never raises, for the same reason _poll_ingest doesn't.

    2026-09-20: config is now fetched fresh via get_effective_config()
    at the start of each tick, for the same reason and in the same way
    as _poll_ingest's own fix -- see its docstring and DECISION_LOG.md.
    A fetch failure here skips this tick's nudge AND escalation work
    (both need a config), logged once, rather than only one of them
    silently running against no config."""
    today = date.today()
    try:
        config = ChannelConfigStore().get_effective_config(CHANNEL_ID, db_path=db_path)
    except Exception as exc:  # noqa: BLE001
        _log(f"[nudge] FAILED -- could not load live config -- {type(exc).__name__}: {exc}")
        _log(f"[escalation] SKIPPED -- config load failed this tick")
        return

    try:
        nudge_results = run_nudge_job(CHANNEL_ID, config, publisher, day=today, db_path=db_path)
        for r in nudge_results:
            who = r.member_id or "(channel-level)"
            _log(f"[nudge] {r.date} {who}: {r.status} -- {r.detail}")
    except Exception as exc:  # noqa: BLE001
        _log(f"[nudge] FAILED -- {type(exc).__name__}: {exc}")

    try:
        escalation_results = run_escalation_job(CHANNEL_ID, config, publisher, day=today, db_path=db_path)
        for r in escalation_results:
            who = r.member_id or "(channel-level)"
            _log(f"[escalation] {r.date} {who}: {r.status} -- {r.detail}")
    except Exception as exc:  # noqa: BLE001
        _log(f"[escalation] FAILED -- {type(exc).__name__}: {exc}")


def main() -> int:
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not tenant_id or not client_id or not team_id:
        print("AZURE_TENANT_ID, AZURE_CLIENT_ID, and GRAPH_TEAM_ID must all be set in .env.")
        return 1

    init_db(LIVE_DB_PATH)
    ChannelConfigStore().sync_to_db(LIVE_DB_PATH)
    config = ChannelConfigStore().get_channel_config(CHANNEL_ID)
    gateway = LLMGateway()
    publisher = get_teams_publisher()

    _log(f"Starting live runner for {config.display_name} ({CHANNEL_ID})")
    _log(f"  ingest poll: every {INGEST_POLL_MINUTES} min")
    _log(f"  daily digest: {config.daily_digest_time} {config.timezone}, working days {config.working_days}")
    _log(f"  nudge/escalation check: {config.update_window_end} {config.timezone} (end of update window)")

    # Seeds the token cache interactively, right here in the foreground,
    # if it doesn't exist yet -- the one place in this whole process an
    # interactive prompt is ever allowed to block, since this is startup,
    # in the main thread, with a person watching the terminal.
    try:
        get_access_token(tenant_id=tenant_id, client_id=client_id, allow_interactive=True)
        _log("Graph token cache OK.")
    except GraphAuthError as exc:
        print(f"Could not obtain an initial Graph token: {exc}")
        return 1

    # The existing, already-tested production scheduler -- this is the
    # first caller anywhere in the codebase to actually .start() it.
    scheduler = build_scheduler([config], gateway, publisher, db_path=LIVE_DB_PATH)

    scheduler.add_job(
        _poll_ingest,
        trigger=IntervalTrigger(minutes=INGEST_POLL_MINUTES),
        id=f"ingest_poll:{CHANNEL_ID}",
        kwargs={
            "tenant_id": tenant_id, "client_id": client_id, "team_id": team_id,
            "gateway": gateway, "db_path": LIVE_DB_PATH,
        },
        next_run_time=datetime.now(),  # run one immediately, don't wait a full interval
    )

    day_of_week = ",".join(_DAY_NAMES[d] for d in config.working_days if d in _DAY_NAMES)
    scheduler.add_job(
        _run_nudges_and_escalations,
        trigger=CronTrigger(
            day_of_week=day_of_week,
            hour=config.update_window_end.hour,
            minute=config.update_window_end.minute,
            timezone=ZoneInfo(config.timezone),
        ),
        id=f"nudge_escalation:{CHANNEL_ID}",
        kwargs={"publisher": publisher, "db_path": LIVE_DB_PATH},
    )

    scheduler.start()
    _log("Scheduler started. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        _log("Stopping...")
        scheduler.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
