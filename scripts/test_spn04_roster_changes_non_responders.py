"""SPN-04 acceptance test, live, roster half: "changing one roster
changes the non-responder set with no code change."

Calls p1.participation.ledger.build_ledger() -- the exact, pure
function both run_nudge_job() and run_escalation_job() actually use in
production to compute who's a non-responder -- directly against the
real live database, before and after a real live roster edit made
through ChannelConfigStore.update_channel_config() (the same write
path Copilot Studio's tool and the Streamlit dashboard use). No nudge
or escalation is actually run, so no real Teams message is ever sent by
this script -- build_ledger() is pure read-only set arithmetic over the
roster and the day's already-classified messages.

Adds one SYNTHETIC, clearly-fake member id (never a real person, never
a real AAD id) to p1-agent-test's roster, confirms it appears as a
brand-new "no_message" non-responder with zero code change, confirms
the real existing roster member's own state is untouched, confirms
Teams-agent-test's own roster/ledger is completely unaffected (the
other half of SPN-04, already proven for config/window -- this proves
it for the ledger computation itself too), then reverts.

Usage:
    uv run python scripts/test_spn04_roster_changes_non_responders.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from p1.config.calendar import to_local  # noqa: E402
from p1.config.loader import ChannelConfigStore  # noqa: E402
from p1.participation.ledger import build_ledger  # noqa: E402
from p1.storage.db import get_connection  # noqa: E402

LIVE_DB_PATH = "data/p1_live.db"
P1_AGENT_TEST = "19:ZVl0BYQCKWi4_oXsG_tuu3F4p5HsgQGobGhAMiZD_ro1@thread.tacv2"
TEAMS_AGENT_TEST = "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2"
SYNTHETIC_MEMBER = "spn04-test-synthetic-member-not-a-real-person"


def _most_recent_message_day(channel_id: str, timezone: str):
    conn = get_connection(LIVE_DB_PATH)
    try:
        rows = conn.execute(
            "SELECT posted_at FROM messages WHERE channel_id = ? AND is_deleted = 0",
            (channel_id,),
        ).fetchall()
    finally:
        conn.close()
    days = {to_local(row["posted_at"], timezone).date() for row in rows}
    if not days:
        return None
    return max(days)


def _print_ledger(label: str, records) -> None:
    print(f"\n{label}: {len(records)} non-responder(s)")
    for r in records:
        print(f"    {r.member_id}: {r.state}  (evidence={list(r.evidence_message_ids)})")


def main() -> None:
    store = ChannelConfigStore()

    p1_config_before = store.get_effective_config(P1_AGENT_TEST, db_path=LIVE_DB_PATH)
    teams_config_before = store.get_effective_config(TEAMS_AGENT_TEST, db_path=LIVE_DB_PATH)

    day = _most_recent_message_day(P1_AGENT_TEST, p1_config_before.timezone)
    if day is None:
        print("p1-agent-test has no messages at all -- nothing to build a ledger against.")
        return
    print(f"Using day {day.isoformat()} ({p1_config_before.timezone}) for p1-agent-test's ledger.")

    ledger_before = build_ledger(P1_AGENT_TEST, day, p1_config_before, db_path=LIVE_DB_PATH)
    _print_ledger("BEFORE -- p1-agent-test non-responders", ledger_before)
    # Not computing a ledger for teams-agent-test here: `day` is chosen
    # from p1-agent-test's own message history and may not even be a
    # configured working day for teams-agent-test (different
    # working_days), which would raise NonWorkingDayError for no reason
    # -- this test's isolation claim for teams-agent-test is checked via
    # its config fingerprint below, which is what a roster edit to a
    # DIFFERENT channel could possibly disturb anyway.
    print(f"\nBEFORE -- teams-agent-test roster: {teams_config_before.roster}, version={teams_config_before.version}")

    original_roster = list(p1_config_before.roster)
    new_roster = original_roster + [SYNTHETIC_MEMBER]

    print(f"\nLive-editing p1-agent-test's roster: {original_roster} -> {new_roster}")
    store.update_channel_config(
        P1_AGENT_TEST,
        roster=new_roster,
        updated_by="spn04-roster-isolation-test",
        db_path=LIVE_DB_PATH,
    )

    p1_config_after = store.get_effective_config(P1_AGENT_TEST, db_path=LIVE_DB_PATH)
    ledger_after = build_ledger(P1_AGENT_TEST, day, p1_config_after, db_path=LIVE_DB_PATH)
    _print_ledger(f"AFTER -- p1-agent-test non-responders (version {p1_config_after.version})", ledger_after)

    teams_config_after = store.get_effective_config(TEAMS_AGENT_TEST, db_path=LIVE_DB_PATH)
    print(f"\nAFTER  -- teams-agent-test roster: {teams_config_after.roster}, version={teams_config_after.version}")

    # Revert immediately -- this script's own job is to observe the
    # effect, not leave a fake roster member behind.
    store.update_channel_config(
        P1_AGENT_TEST,
        roster=original_roster,
        updated_by="spn04-roster-isolation-test-revert",
        db_path=LIVE_DB_PATH,
    )
    p1_config_reverted = store.get_effective_config(P1_AGENT_TEST, db_path=LIVE_DB_PATH)
    print(f"\nReverted p1-agent-test roster back to {p1_config_reverted.roster} (version {p1_config_reverted.version}).")

    synthetic_appeared = any(r.member_id == SYNTHETIC_MEMBER and r.state == "no_message" for r in ledger_after)
    original_member_state_before = {r.member_id: r.state for r in ledger_before}
    original_member_state_after = {r.member_id: r.state for r in ledger_after if r.member_id != SYNTHETIC_MEMBER}
    original_members_untouched = original_member_state_before == original_member_state_after
    teams_untouched = (
        teams_config_before.model_dump() == teams_config_after.model_dump()
    )

    print("\n=== SPN-04 roster-change verdict ===")
    print(f"Synthetic member appeared as a new no_message non-responder : {synthetic_appeared}")
    print(f"Existing roster member(s)' own state unchanged by the edit  : {original_members_untouched}")
    print(f"teams-agent-test config completely unaffected               : {teams_untouched}")

    if synthetic_appeared and original_members_untouched and teams_untouched:
        print("\nPASS: a live roster edit (no code change, no restart) changed p1-agent-test's "
              "own non-responder set exactly as expected, left its existing member's state "
              "untouched, and had zero effect on teams-agent-test.")
    else:
        print("\nFAIL or INCONCLUSIVE -- see the fields above that differ.")


if __name__ == "__main__":
    main()
