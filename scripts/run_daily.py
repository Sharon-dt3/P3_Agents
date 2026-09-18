"""
Daily run entry point (CHN-31): the real, tested full flow, run once
end to end against the committed mock fixtures -- proof, for a fresh
clone, that the whole pipeline genuinely works against the mock Teams
adapter with zero Graph/tenant credentials.

For every allowlisted channel (config/channels/*.yaml,
allowlisted: true), on the one committed fixture date this script fixes
(DEMO_DAY, below): ingest the committed mock messages (the same fixture
data scripts/generate_seed_fixtures.py produced), run CHN-08/09
detection (rules first, the model only for what a rule left unsettled),
build CHN-10's participation ledger, and generate and publish
CHN-13/17's daily digest through
p1.publishing.daily_job.run_daily_digest_job -- the exact same function
every unit test, GC6, and CHN-24/27's own real runs already exercise,
never a second, separately maintained demo path.

This is a one-shot manual run, not a standalone always-on scheduler:
wiring p1.publishing.scheduler's clock into a long-running per-channel
process is still real, undone work (see README.md's Status table, C7)
-- out of this row's scope, which is proving the mock-path flow itself
runs clean, not building a production daemon.

The only external dependency this script has is ANTHROPIC_API_KEY (in
.env) -- p1.reporting.daily_summary asks the model to turn
already-computed facts into prose for every non-empty section, so a
real digest genuinely needs one real model call; that is normal
operation, not a gap (see that module's own docstring). It is a
separate axis entirely from Microsoft Graph / Teams tenant access,
which this script never touches: TEAMS_READER_MODE and
TEAMS_PUBLISHER_MODE both default to "mock" (p1.adapters.factory), so
no GRAPH_* variable is read anywhere on this path. If ANTHROPIC_API_KEY
is missing, p1.llm.gateway.LLMGateway's own designed degrade-to-Ollama
fallback (SPN-02) means the error surfaced may be an Ollama connection
failure rather than a plain "no API key" message -- that is existing,
documented gateway behaviour, not something this script introduces;
see DECISION_LOG.md's CHN-31 entry.

Member rows are inserted directly from the fixture data, exactly as
every golden-case eval module already does (see e.g.
p1.eval.chn24_cases) -- CHN-05's ingestion orchestrator
(sync_all_allowlisted_channels) drains messages from a TeamsReader but
has never had a member-sync capability of its own, mock or Graph; that
is a real, pre-existing gap this script works around the same
already-established way the eval harness does, not a new one, and not
silently fixed here -- see DECISION_LOG.md.

run_full_flow() is the importable, dependency-injectable body (gateway
and publisher can both be substituted) -- tests/unit/test_run_daily_full_flow.py
calls it directly with a scripted gateway, never a live model call, the
same discipline this project's own verification rule holds every other
row to.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

# Ensure `src/` is importable regardless of how this script is invoked --
# same workaround run_eval.py and seed.py already use (see DECISION_LOG.md).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from p1.adapters.factory import get_teams_publisher
from p1.adapters.fixtures import load_teams_fixtures
from p1.adapters.teams_publisher_mock import DEFAULT_LOG_PATH
from p1.config.loader import ChannelConfigStore
from p1.detection.pipeline import classify_and_persist
from p1.llm.gateway import LLMGateway
from p1.publishing.daily_job import JobResult, run_daily_digest_job
from p1.storage.db import DEFAULT_DB_PATH, get_connection, init_db
from p1.storage.messages_repo import MessageStore

# The committed fixture window (seed/fixtures/, seed=42) runs
# 2025-06-02 through 2025-06-13. 2025-06-11 is an ordinary working
# Wednesday, mid-window (not either channel's first or last day), with
# real on-time updates and real non-responders on both allowlisted
# channels -- neither the emptiest nor the most contrived day available.
DEMO_DAY = date(2025, 6, 11)


def run_full_flow(
    *,
    db_path: str | Path = DEFAULT_DB_PATH,
    gateway=None,
    publisher=None,
    day: date = DEMO_DAY,
) -> list[JobResult]:
    init_db(db_path)

    config_store = ChannelConfigStore()
    config_store.sync_to_db(db_path)
    channel_ids = config_store.list_allowlisted_channels()

    _, _, messages_by_channel = load_teams_fixtures()

    conn = get_connection(db_path)
    try:
        author_ids = sorted(
            {
                m.author_id
                for cid in channel_ids
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

    gateway = gateway or LLMGateway()
    publisher = publisher or get_teams_publisher()
    message_store = MessageStore(db_path)

    results: list[JobResult] = []
    for channel_id in channel_ids:
        config = config_store.get_channel_config(channel_id)
        channel_messages = messages_by_channel.get(channel_id, [])
        message_store.upsert_messages(channel_messages)
        classify_and_persist(channel_messages, config, gateway, db_path=db_path)

        result = run_daily_digest_job(
            channel_id, config, gateway, publisher, day=day, db_path=db_path,
        )
        print(f"[run] {config.display_name} ({channel_id}) {day.isoformat()}: {result.status} -- {result.detail}")
        results.append(result)

    log_path = os.environ.get("TEAMS_PUBLISHER_LOG_PATH", str(DEFAULT_LOG_PATH))
    print(f"[run] Outbound log (mock publisher, inspectable): {log_path}")
    return results


def main() -> int:
    run_full_flow()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
