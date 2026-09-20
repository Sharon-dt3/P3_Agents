"""
Live proof that messages_fts (2026-09-20's fix) actually works now: runs
a real FTS5 MATCH query against whatever real content is currently in
data/p1_live.db for p1-agent-test, printing each hit with its permalink.

Calling init_db() here is what actually applies migration
0006_messages_fts_sync.sql (triggers + one-time rebuild) if it hasn't
run against this db yet -- so this script alone is enough to prove the
fix, independent of whether scripts/live_runner_p1_agent_test.py has
been restarted.

Usage:
    uv run python scripts/search_messages_p1_agent_test.py wiring
    uv run python scripts/search_messages_p1_agent_test.py "no blockers"
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.storage.db import get_connection, init_db

LIVE_DB_PATH = "data/p1_live.db"
CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test


def main() -> int:
    if len(sys.argv) < 2:
        print('Usage: uv run python scripts/search_messages_p1_agent_test.py "search terms"')
        return 1
    query = sys.argv[1]

    init_db(LIVE_DB_PATH)  # applies 0006 (triggers + rebuild) if not already applied
    conn = get_connection(LIVE_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.posted_at, m.is_bot, m.permalink, m.body_normalized
            FROM messages_fts
            JOIN messages m ON m.rowid = messages_fts.rowid
            WHERE messages_fts MATCH ? AND m.channel_id = ?
            ORDER BY m.posted_at DESC
            """,
            (query, CHANNEL_ID),
        ).fetchall()
    finally:
        conn.close()

    print(f"Search for {query!r} in p1-agent-test: {len(rows)} hit(s)\n")
    for row in rows:
        who = "bot" if row["is_bot"] else "human"
        print(f"[{row['posted_at']}] ({who}) {row['body_normalized'][:100]}")
        print(f"    {row['permalink']}\n")

    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
