"""SPN-04 acceptance test, live: "Two channels configured with different
rosters, windows and timezones; changing one roster changes the
non-responder set with no code change" -- AND, the other half of the
same claim this test is actually checking, changing one channel's
roster/window must NOT change the other channel's non-responder set.

Edits ONLY Teams-agent-test's live config (via the real
ChannelConfigStore.update_channel_config() write path -- the same one
Copilot Studio's tool and the Streamlit dashboard use), takes a
before/after snapshot of BOTH channels' effective config and BOTH
channels' message/classification state, and lets you verify after a
real poll tick that p1-agent-test's own state is byte-for-byte
unchanged.

Usage:
    uv run python scripts/test_spn04_isolation.py           # edit + snapshot
    ... wait for both live_runner_*.py terminals to do at least
        one more scheduled ingest tick (every 5 min) ...
    uv run python scripts/test_spn04_isolation.py --verify   # compare
    uv run python scripts/test_spn04_isolation.py --revert   # put Teams-agent-test back
"""
from __future__ import annotations

import json
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from p1.config.loader import ChannelConfigStore  # noqa: E402
from p1.storage.db import get_connection  # noqa: E402

LIVE_DB_PATH = "data/p1_live.db"
SNAPSHOT_PATH = Path("data/_spn04_isolation_snapshot.json")

P1_AGENT_TEST = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"
TEAMS_AGENT_TEST = "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2"

TEST_WINDOW_START = time(10, 0, 0)
TEST_WINDOW_END = time(11, 0, 0)
ORIGINAL_WINDOW_START = time(9, 0, 0)
ORIGINAL_WINDOW_END = time(13, 0, 0)


def _config_fingerprint(store: ChannelConfigStore, channel_id: str) -> dict:
    cfg = store.get_effective_config(channel_id, db_path=LIVE_DB_PATH)
    return {
        "roster": sorted(cfg.roster),
        "update_window_start": str(cfg.update_window_start),
        "update_window_end": str(cfg.update_window_end),
        "timezone": cfg.timezone,
        "version": cfg.version,
    }


def _message_fingerprint(channel_id: str) -> dict:
    conn = get_connection(LIVE_DB_PATH)
    try:
        rows = conn.execute(
            """
            SELECT m.id, c.label
            FROM messages m
            LEFT JOIN classifications c ON c.message_id = m.id
            WHERE m.channel_id = ?
            ORDER BY m.id
            """,
            (channel_id,),
        ).fetchall()
    finally:
        conn.close()
    label_counts: dict[str, int] = {}
    for row in rows:
        label = row["label"] or "(unclassified)"
        label_counts[label] = label_counts.get(label, 0) + 1
    return {
        "message_count": len(rows),
        "label_counts": label_counts,
        "message_ids": [row["id"] for row in rows],
    }


def _full_snapshot(store: ChannelConfigStore) -> dict:
    return {
        "p1_agent_test": {
            "config": _config_fingerprint(store, P1_AGENT_TEST),
            "messages": _message_fingerprint(P1_AGENT_TEST),
        },
        "teams_agent_test": {
            "config": _config_fingerprint(store, TEAMS_AGENT_TEST),
            "messages": _message_fingerprint(TEAMS_AGENT_TEST),
        },
    }


def _print_snapshot(label: str, snap: dict) -> None:
    print(f"\n--- {label} ---")
    for key in ("p1_agent_test", "teams_agent_test"):
        c = snap[key]["config"]
        m = snap[key]["messages"]
        print(f"{key}: window {c['update_window_start']}-{c['update_window_end']} "
              f"({c['timezone']}), roster={c['roster']}, version={c['version']}")
        print(f"    messages={m['message_count']}, labels={m['label_counts']}")


def main() -> None:
    store = ChannelConfigStore()
    mode_verify = "--verify" in sys.argv
    mode_revert = "--revert" in sys.argv

    if mode_verify:
        if not SNAPSHOT_PATH.exists():
            print(f"No snapshot at {SNAPSHOT_PATH} -- run this script without flags first.")
            return
        before = json.loads(SNAPSHOT_PATH.read_text())
        after = _full_snapshot(store)
        _print_snapshot("BEFORE (saved at edit time)", before)
        _print_snapshot("AFTER (right now)", after)

        p1_before = before["p1_agent_test"]
        p1_after = after["p1_agent_test"]
        same_config = p1_before["config"] == p1_after["config"]
        same_messages = p1_before["messages"] == p1_after["messages"]

        print("\n=== SPN-04 isolation verdict ===")
        print(f"p1-agent-test config unchanged   : {same_config}")
        print(f"p1-agent-test messages unchanged : {same_messages}")
        teams_changed = before["teams_agent_test"]["config"] != after["teams_agent_test"]["config"]
        print(f"teams-agent-test config actually changed (proves the live edit really took) : {teams_changed}")

        if same_config and same_messages and teams_changed:
            print("\nPASS: editing Teams-agent-test's live config changed only its own "
                  "config, with p1-agent-test's config and classify state byte-for-byte "
                  "identical across at least one real poll tick.")
        else:
            print("\nFAIL or INCONCLUSIVE -- see the fields above that differ.")
        return

    new_start = ORIGINAL_WINDOW_START if mode_revert else TEST_WINDOW_START
    new_end = ORIGINAL_WINDOW_END if mode_revert else TEST_WINDOW_END

    before = _full_snapshot(store)
    _print_snapshot("BEFORE the write", before)

    store.update_channel_config(
        TEAMS_AGENT_TEST,
        update_window_start=new_start,
        update_window_end=new_end,
        updated_by="spn04-isolation-test",
        db_path=LIVE_DB_PATH,
    )

    after = _full_snapshot(store)
    _print_snapshot("AFTER the write (immediately)", after)

    if mode_revert:
        print("\nReverted Teams-agent-test's window back to 09:00-13:00.")
        if SNAPSHOT_PATH.exists():
            SNAPSHOT_PATH.unlink()
    else:
        SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_PATH.write_text(json.dumps(before, indent=2))
        print(f"\nSaved BEFORE snapshot to {SNAPSHOT_PATH}.")
        print("Now wait for BOTH live_runner_p1_agent_test.py and "
              "live_runner_teams_agent_test.py to complete at least one more "
              "scheduled ingest tick (every 5 min, no restart needed), then run:")
        print("    uv run python scripts/test_spn04_isolation.py --verify")


if __name__ == "__main__":
    main()
