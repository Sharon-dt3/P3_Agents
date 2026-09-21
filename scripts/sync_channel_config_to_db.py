"""
Pushes config/channels/*.yaml into the live channel_config table via
ChannelConfigStore.sync_to_db() -- the "redeploy" bootstrap loader.py's
own docstring describes: it resets every field, for every channel, to
whatever's currently committed in YAML.

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

Usage:
    uv run python scripts/sync_channel_config_to_db.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from p1.config.loader import ChannelConfigStore, DEFAULT_DB_PATH


def _snapshot(store: ChannelConfigStore, channel_id: str, db_path) -> str:
    try:
        c = store.get_effective_config(channel_id, db_path=db_path)
    except KeyError:
        return f"  {channel_id}: no row in DB yet"
    return (
        f"  {channel_id}: nudge_enabled={c.nudge_enabled} "
        f"update_window={c.update_window_start}-{c.update_window_end} "
        f"working_days={c.working_days} version={c.version}"
    )


def main() -> int:
    store = ChannelConfigStore()
    configured = store.list_configured_channels()
    channel_ids = [c.channel_id for c in configured]

    print(f"Committed config files: {len(configured)} channel(s) under {store.config_dir}/")
    print("\nBEFORE:")
    for cid in channel_ids:
        print(_snapshot(store, cid, DEFAULT_DB_PATH))

    n = store.sync_to_db(db_path=DEFAULT_DB_PATH)

    print(f"\nSynced {n} channel(s) from committed YAML into {DEFAULT_DB_PATH}.")
    print("\nAFTER:")
    for cid in channel_ids:
        print(_snapshot(store, cid, DEFAULT_DB_PATH))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
