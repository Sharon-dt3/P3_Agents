"""
The live, always-on process for the two demo channels (AI Agent -
Delivery Standup and AI Agent -- Platform Standup) -- the same pattern
live_runner_p1_agent_test.py already proved out for a single channel,
generalized here to run several channels in one process instead of
hardcoding one CHANNEL_ID. Nothing about the underlying jobs changes:
this script only parametrizes what live_runner_p1_agent_test.py already
does, so the two demo channels get the identical real behaviour
(ingestion polling, the daily digest scheduler, nudge-then-escalation at
end of update window) that channel has already had live-verified.

Leave this running in a terminal for the days you're seeding the demo
(Sharon posts a real update, Himanshu posts something that doesn't
count, Esandu stays silent) -- it does not exit on its own.

Three independent things run per channel, in one process:

  1. Ingestion polling, every INGEST_POLL_MINUTES (default 5): fetches a
     fresh Graph token and calls sync_channel() for that channel, then
     re-syncs thread replies for every known root -- identical to
     live_runner_p1_agent_test.py's own _poll_ingest, just looped over
     CHANNEL_IDS instead of one constant.

  2. The daily digest job, via p1.publishing.scheduler.build_scheduler()
     -- this already accepts a LIST of configs (see
     live_runner_p1_agent_test.py's own call site, which just happens to
     pass a list of one), so both channels' digest jobs are registered
     by the same single build_scheduler([...]) call here.

  3. Nudges, then escalation, once per configured working day at THAT
     channel's own update_window_end -- registered once per channel
     (they don't have to share a time; each channel's own config decides
     its own tick). AI Agent -- Platform Standup has nudge_enabled=False,
     so its tick logs "disabled" and returns immediately every time --
     harmless, not an error, exactly like run_nudge_job's own DISABLED
     status is designed to be.

Each channel's ScopedTeamsReader is allowlisted against CHANNEL_IDS (both
demo channels this process manages), not the full set of every
allowlisted channel in config/channels/ -- least privilege, same posture
live_runner_p1_agent_test.py takes by allowlisting only itself.

Usage:
    uv run python scripts/graph_seed_token_cache.py   # once, first time only, if not already done
    uv run python scripts/live_runner_demo_channels.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

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
from p1.ingestion.sync import sync_channel, sync_channel_replies
from p1.llm.gateway import LLMGateway
from p1.nudges.nudge_job import run_nudge_job
from p1.publishing.scheduler import build_scheduler
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore
from p1.storage.sync_state import SyncStateStore

LIVE_DB_PATH = os.environ.get("P1_DB_PATH", "data/p1_live.db")

CHANNEL_IDS = [
    "19:cjXUoeQ-LwPPkGYen8aHJa7atEdh9krnVo-urM6Gkxs1@thread.tacv2",  # AI Agent - Delivery Standup
    "19:onXXPocFXdrTt8Krz3p2GnNrpNo9p1HBHXQxzFsWOmk1@thread.tacv2",  # AI Agent -- Platform Standup
]

INGEST_POLL_MINUTES = int(os.environ.get("INGEST_POLL_MINUTES", "5"))

_DAY_NAMES = {
    "Mon": "mon", "Tue": "tue", "Wed": "wed", "Thu": "thu",
    "Fri": "fri", "Sat": "sat", "Sun": "sun",
}


def _log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _load_channel_messages(db_path: str, channel_id: str) -> list[TeamsMessage]:
    """Reconstructs TeamsMessage objects from every non-deleted row this
    channel currently has in `messages` -- identical to
    live_runner_p1_agent_test.py's own helper of the same name."""
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


def _poll_ingest(*, channel_id: str, tenant_id: str, client_id: str, team_id: str, gateway, db_path: str) -> None:
    """One ingestion tick for ONE channel -- identical logic to
    live_runner_p1_agent_test.py's own _poll_ingest, just parametrized on
    channel_id instead of reading a module-level constant. Never raises."""
    try:
        access_token = get_access_token(
            tenant_id=tenant_id, client_id=client_id, allow_interactive=False,
        )
    except GraphAuthError as exc:
        _log(f"[{channel_id}] [ingest] SKIPPED -- {exc}")
        return

    try:
        config = ChannelConfigStore().get_effective_config(channel_id, db_path=db_path)
        raw_reader = GraphTeamsReader(access_token=access_token, team_id=team_id)
        reader = ScopedTeamsReader(raw_reader, allowlisted_channel_ids=CHANNEL_IDS, db_path=db_path)
        sync_state = SyncStateStore(db_path)
        message_store = MessageStore(db_path)
        result = sync_channel(reader, channel_id, sync_state, message_store)
        note = " (resynced from scratch)" if result.resynced else ""
        _log(f"[{channel_id}] [ingest] {result.messages_ingested} new message(s){note}")

        root_ids = message_store.list_root_message_ids(channel_id)
        for root_id in root_ids:
            reader.note_known_message(root_id, channel_id)
        reply_count = sync_channel_replies(reader, channel_id, root_ids, message_store)
        _log(f"[{channel_id}] [ingest] {reply_count} reply message(s) synced across {len(root_ids)} thread(s)")

        messages = _load_channel_messages(db_path, channel_id)
        outcomes = classify_and_persist(messages, config, gateway, db_path=db_path)
        noise_count = sum(1 for o in outcomes if o.label == "noise")
        _log(
            f"[{channel_id}] [classify] {len(outcomes)} message(s) evaluated: "
            f"{len(outcomes) - noise_count} signal, {noise_count} noise"
        )
    except Exception as exc:  # noqa: BLE001 -- a poll tick must never crash the scheduler thread
        _log(f"[{channel_id}] [ingest] FAILED -- {type(exc).__name__}: {exc}")


def _run_nudges_and_escalations(*, channel_id: str, publisher, db_path: str) -> None:
    """One end-of-window tick for ONE channel -- nudges first, escalation
    immediately after, identical logic to live_runner_p1_agent_test.py's
    own _run_nudges_and_escalations. For AI Agent -- Platform Standup
    (nudge_enabled=False) this logs DISABLED and returns -- not an
    error, the same harmless no-op run_nudge_job already documents."""
    today = date.today()
    try:
        config = ChannelConfigStore().get_effective_config(channel_id, db_path=db_path)
    except Exception as exc:  # noqa: BLE001
        _log(f"[{channel_id}] [nudge] FAILED -- could not load live config -- {type(exc).__name__}: {exc}")
        _log(f"[{channel_id}] [escalation] SKIPPED -- config load failed this tick")
        return

    try:
        nudge_results = run_nudge_job(channel_id, config, publisher, day=today, db_path=db_path)
        for r in nudge_results:
            who = r.member_id or "(channel-level)"
            _log(f"[{channel_id}] [nudge] {r.date} {who}: {r.status} -- {r.detail}")
    except Exception as exc:  # noqa: BLE001
        _log(f"[{channel_id}] [nudge] FAILED -- {type(exc).__name__}: {exc}")

    try:
        escalation_results = run_escalation_job(channel_id, config, publisher, day=today, db_path=db_path)
        for r in escalation_results:
            who = r.member_id or "(channel-level)"
            _log(f"[{channel_id}] [escalation] {r.date} {who}: {r.status} -- {r.detail}")
    except Exception as exc:  # noqa: BLE001
        _log(f"[{channel_id}] [escalation] FAILED -- {type(exc).__name__}: {exc}")


def main() -> int:
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    team_id = os.environ.get("GRAPH_TEAM_ID")
    if not tenant_id or not client_id or not team_id:
        print("AZURE_TENANT_ID, AZURE_CLIENT_ID, and GRAPH_TEAM_ID must all be set in .env.")
        return 1

    init_db(LIVE_DB_PATH)
    ChannelConfigStore().sync_to_db(LIVE_DB_PATH)

    configs = [ChannelConfigStore().get_channel_config(cid) for cid in CHANNEL_IDS]
    gateway = LLMGateway()
    publisher = get_teams_publisher()

    _log(f"Starting live runner for {len(configs)} demo channel(s):")
    for config in configs:
        _log(
            f"  {config.display_name} ({config.channel_id}) -- "
            f"nudge_enabled={config.nudge_enabled}, daily digest {config.daily_digest_time} {config.timezone}, "
            f"working days {config.working_days}"
        )
    _log(f"  ingest poll: every {INGEST_POLL_MINUTES} min, per channel")

    try:
        get_access_token(tenant_id=tenant_id, client_id=client_id, allow_interactive=True)
        _log("Graph token cache OK.")
    except GraphAuthError as exc:
        print(f"Could not obtain an initial Graph token: {exc}")
        return 1

    # build_scheduler already accepts a list of configs -- both channels'
    # daily digest jobs are registered by this one call.
    scheduler = build_scheduler(configs, gateway, publisher, db_path=LIVE_DB_PATH)

    for config in configs:
        scheduler.add_job(
            _poll_ingest,
            trigger=IntervalTrigger(minutes=INGEST_POLL_MINUTES),
            id=f"ingest_poll:{config.channel_id}",
            kwargs={
                "channel_id": config.channel_id,
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
            id=f"nudge_escalation:{config.channel_id}",
            kwargs={"channel_id": config.channel_id, "publisher": publisher, "db_path": LIVE_DB_PATH},
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
