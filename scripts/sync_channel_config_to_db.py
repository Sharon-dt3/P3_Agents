"""
Pushes config/channels/*.yaml into the live channel_config table via
ChannelConfigStore.sync_to_db() -- the "redeploy" bootstrap. Since
2026-09-23 it re-applies every YAML-only field but leaves a channel's
live owner-editable fields (roster, update window, exceptions) alone;
pass --reset to force those back to YAML too (audited). See loader.py.

Written because tonight's task needs to flip nudge_enabled on
teams-agent-test, and nudge_enabled is deliberately NOT one of the four
fields update_channel_config() can touch live (see loader.py -- only
roster, update_window_start, update_window_end, exceptions are the
owner-editable surface; nudge_enabled, like timezone and digest times,
is committed-YAML-only, changed only by a deploy). sync_to_db() is that
deploy step. There was no existing script that did just this -- the
closest, test_live_config_update_adhoc.py, deliberately only exercises
update_channel_config() itself, to prove the *other* thing (that a
live edit bypasses a deploy). This script is the deploy side.

Safe to run repeatedly, same as every other script in this project:
sync_to_db() upserts, it doesn't append, and running it twice with an
unchanged YAML is a no-op against the DB (still bumps updated_at, not
version -- version only moves through update_channel_config()).

Prints each configured channel's four live-relevant fields before and
after, so you can see exactly what changed and confirm nothing else on
the other channel moved.

2026-09-23 finding (same class of bug as approval_dashboard.py's
2026-09-19 finding, see that file's own docstring): this script never
called load_dotenv(), so P1_DB_PATH from .env was never read into
os.environ before DEFAULT_DB_PATH's import-time fallback
("data/p1.db") was used -- every run silently synced into a fresh,
migration-less DB next to the real data/p1_live.db every other live
script actually reads, instead of the live one, and failed outright
with "no such table: channel_config" since data/p1.db had never had
run_migrations() applied to it at all. Fixed the same way
approval_dashboard.py was: load .env, then read P1_DB_PATH with the
same fallback-to-DEFAULT_DB_PATH pattern every other live-facing
script in this repo already uses.

Usage:
    uv run python scripts/sync_channel_config_to_db.py
    uv run python scripts/sync_channel_config_to_db.py --reset   # YAML also wins for owner-edited fields
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.config.loader import ChannelConfigStore, DEFAULT_DB_PATH

DB_PATH = os.environ.get("P1_DB_PATH", DEFAULT_DB_PATH)


def _snapshot(store: ChannelConfigStore, channel_id: str, db_path) -> str:
    try:
        c = store.get_effective_config(channel_id, db_path=db_path)
    except KeyError:
        return f"  {channel_id}: no row in DB yet"
    return (
        f"  {channel_id}: nudge_enabled={c.nudge_enabled} "
        f"roster={len(c.roster)} update_window={c.update_window_start}-{c.update_window_end} "
        f"working_days={c.working_days} version={c.version}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reset", action="store_true",
        help="also overwrite live roster/window/exceptions edits with the committed YAML",
    )
    args = parser.parse_args()

    store = ChannelConfigStore()
    configured = store.list_configured_channels()
    channel_ids = [c.channel_id for c in configured]

    print(f"Committed config files: {len(configured)} channel(s) under {store.config_dir}/")
    print(f"Target database: {DB_PATH}")
    print("\nBEFORE:")
    for cid in channel_ids:
        print(_snapshot(store, cid, DB_PATH))

    n = store.sync_to_db(db_path=DB_PATH, reset_owner_fields=args.reset)

    print(f"\nSynced {n} channel(s) from committed YAML into {DB_PATH}.")
    print("\nAFTER:")
    for cid in channel_ids:
        print(_snapshot(store, cid, DB_PATH))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
