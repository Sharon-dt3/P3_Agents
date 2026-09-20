"""One-off maintenance: wipe a channel's daily-digest history for specific
calendar days so the pipeline can regenerate them from scratch.

Why this exists: DigestStore.has_ever_published(channel_id) is a
whole-channel flag, not per-day -- clearing one day alone never un-sets
it if any OTHER day for that channel still has published_at set (see
p1.storage.digests_repo.has_ever_published's own docstring). This
script only removes rows for the exact days you name; it does not
reset the channel-wide flag unless every published day is named.

Safety, deliberately layered because this is real deletion against a
real live database:

1. Dry run by default. Nothing is deleted unless you pass --confirm.
2. A timestamped copy of the whole db is made before any write, every
   time, confirm run or not skipped.
3. Every row this would touch is printed by id/idempotency_key before
   deletion, both in dry-run and confirm mode.
4. Only rows for the exact (channel_id, day) pairs you name are ever
   touched -- proposals, digests, write_log (via proposal_id), and
   audit (via entity_id), nothing else.

Run this from your own terminal, not through any remote bridge --
SQLite needs to delete its own journal file as part of a clean commit,
and a bridge without local delete permission can leave a stale journal
behind that makes the database unreadable until it's cleaned up by
hand (see chat, 2026-09-20).

Usage:
    uv run python scripts/reset_daily_digest_days.py --day 2026-09-20 --day 2026-09-21
    uv run python scripts/reset_daily_digest_days.py --day 2026-09-20 --day 2026-09-21 --confirm
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

import os

from p1.storage.db import DEFAULT_DB_PATH

DEFAULT_CHANNEL = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"  # p1-agent-test


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", default=os.environ.get("P1_DB_PATH", str(DEFAULT_DB_PATH)))
    parser.add_argument("--channel-id", default=DEFAULT_CHANNEL, help=f"default: {DEFAULT_CHANNEL!r} (p1-agent-test)")
    parser.add_argument("--day", action="append", required=True, dest="days", help="YYYY-MM-DD, repeatable")
    parser.add_argument("--confirm", action="store_true", help="actually delete; omit for a dry run")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"no such db: {db_path}")
        return 1

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")  # noqa: DTZ005 -- local wall-clock time for a backup filename, not user-facing data
    backup_path = db_path.with_name(f"{db_path.name}.bak.{stamp}")
    shutil.copy2(db_path, backup_path)
    print(f"backup written: {backup_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    publish_keys = [f"{args.channel_id}:{d}:daily_publish" for d in args.days]
    placeholders = ",".join("?" * len(publish_keys))

    proposals = conn.execute(
        f"SELECT id, status, idempotency_key FROM proposals WHERE idempotency_key IN ({placeholders})",
        publish_keys,
    ).fetchall()
    digests = conn.execute(
        f"SELECT id, date, published_at FROM digests WHERE channel_id = ? AND date IN ({','.join('?' * len(args.days))})",
        [args.channel_id, *args.days],
    ).fetchall()
    prop_ids = [p["id"] for p in proposals]

    print(f"\nWould touch, for {args.channel_id}, days {args.days}:")
    print(f"  proposals ({len(proposals)}):")
    for p in proposals:
        print(f"    {p['id']}  [{p['status']}]  {p['idempotency_key']}")
    print(f"  digests ({len(digests)}):")
    for d in digests:
        print(f"    id={d['id']}  date={d['date']}  published_at={d['published_at']}")

    if prop_ids:
        wl_placeholders = ",".join("?" * len(prop_ids))
        wl_count = conn.execute(
            f"SELECT COUNT(*) FROM write_log WHERE proposal_id IN ({wl_placeholders})", prop_ids
        ).fetchone()[0]
        audit_count = conn.execute(
            f"SELECT COUNT(*) FROM audit WHERE entity_type='proposal' AND entity_id IN ({wl_placeholders})",
            prop_ids,
        ).fetchone()[0]
    else:
        wl_count = audit_count = 0
    print(f"  write_log rows tied to those proposals: {wl_count}")
    print(f"  audit rows tied to those proposals: {audit_count}")

    if not args.confirm:
        print("\nDry run only -- nothing deleted. Re-run with --confirm to actually delete these rows.")
        conn.close()
        return 0

    cur = conn.cursor()
    if prop_ids:
        wl_placeholders = ",".join("?" * len(prop_ids))
        cur.execute(f"DELETE FROM write_log WHERE proposal_id IN ({wl_placeholders})", prop_ids)
        cur.execute(
            f"DELETE FROM audit WHERE entity_type='proposal' AND entity_id IN ({wl_placeholders})", prop_ids
        )
        cur.execute(f"DELETE FROM proposals WHERE id IN ({wl_placeholders})", prop_ids)
    cur.execute(
        f"DELETE FROM digests WHERE channel_id = ? AND date IN ({','.join('?' * len(args.days))})",
        [args.channel_id, *args.days],
    )
    conn.commit()
    conn.close()
    print(f"\nDone. {len(proposals)} proposal(s), {len(digests)} digest(s), {wl_count} write_log row(s), "
          f"{audit_count} audit row(s) deleted. Backup at {backup_path} if you need to undo this.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
