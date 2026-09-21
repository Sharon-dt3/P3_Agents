"""Ad-hoc, safe live test for the "channel owner maintains config
without a deploy" claim (P1 C1 / P2 P6 / P3 O4). Calls the exact same
ChannelConfigStore.update_channel_config() that Copilot Studio's
"Update Channel Config" tool and the Streamlit dashboard call --
nothing here is a shortcut around the real write path.

This deliberately narrows update_window_end to a time already in the
past today, so if the ALREADY-RUNNING live_runner process picks this
change up on its next scheduled ingest poll, some of today's currently
"signal" messages should flip to "outside_update_window" noise on the
next tick. If the counts in live_runner's own terminal output don't
change after the next poll, that is live proof the running process is
still using its frozen startup config, not this live edit.

Only touches update_window_end (one of the three fields this store is
built to let a channel owner change live) and reverts it back to its
original value when re-run with --revert.
"""
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from p1.config.loader import ChannelConfigStore  # noqa: E402

CHANNEL_ID = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"
LIVE_DB_PATH = "data/p1_live.db"
TEST_WINDOW_END = time(12, 0, 0)   # well before "now" today -- deliberately in the past
ORIGINAL_WINDOW_END = time(17, 30, 0)  # matches daily_digest_time, the committed value


def main() -> None:
    store = ChannelConfigStore()
    before = store.get_effective_config(CHANNEL_ID, db_path=LIVE_DB_PATH)
    print(f"BEFORE -- update_window_end in DB: {before.update_window_end}")

    revert = "--revert" in sys.argv
    new_end = ORIGINAL_WINDOW_END if revert else TEST_WINDOW_END

    updated = store.update_channel_config(
        CHANNEL_ID,
        update_window_end=new_end,
        updated_by="live-config-test",
        db_path=LIVE_DB_PATH,
    )
    print(f"AFTER  -- update_window_end in DB: {updated.update_window_end}  (version {updated.version})")

    if revert:
        print("\nReverted. Now watch live_runner's own terminal for its next ingest poll and "
              "check whether classify counts look normal again for a window ending 17:30.")
    else:
        print("\nDone. Now watch the ALREADY-RUNNING live_runner's terminal for its next "
              "scheduled ingest poll (every 5 min) WITHOUT restarting it, and paste back "
              "whatever it prints. If the frozen-config gap is real, the "
              "'[classify] N signal, M noise' counts should stay exactly what they were "
              "before this script ran -- proving the live edit had no effect on the "
              "running process. Run this script again with --revert once you've seen it.")


if __name__ == "__main__":
    main()
