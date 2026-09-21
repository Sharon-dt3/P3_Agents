"""
Pulls channel config edits made in Dataverse's own UI back into
data/p1_live.db, via the one write path CHN-25 already exposes --
ChannelConfigStore.update_channel_config() -- exactly the way
scripts/sync_to_supabase.py mirrors the other direction (SQLite ->
Supabase, read-only for humans). This script is the reverse: Dataverse
(the human-editable surface) -> SQLite (the live system every job and
approval reads), one-way, same as that decision (see DECISION_LOG.md,
"Option B", and claude/dataverse-config-surface-design.md in the p3
Agents project for the full design writeup this implements).

STATUS AS OF 2026-09-21: written but UNTESTED against a real table,
because no real Dataverse table exists yet -- table creation is
greyed out for this account in the "P1 Channel Intelligence" solution
(DigitalT3 Software Services environment) pending a System Customizer
role grant from an admin. This file is what's ready to run the moment
that table exists; until then, running it will fail cleanly at the
auth or fetch step with a clear message, not silently do nothing.

WHY THIS IS SCOPED TO ONLY THREE FIELDS: update_channel_config() (see
src/p1/config/loader.py) only accepts roster, update_window_start,
update_window_end, and exceptions -- every other ChannelConfig field
(timezone, digest times, nudge_cap_per_day, ...) is committed-YAML-only
by design (see that module's own docstring for why). So the three
Dataverse tables below mirror exactly those fields and nothing more --
there is deliberately no p1_channelconfig column for, say, timezone,
because writing one would imply a live edit path that doesn't exist.

TABLE NAMES AND COLUMN LOGICAL NAMES BELOW ARE PLACEHOLDERS. Dataverse
assigns real logical/entity-set names when a table is actually created
in the maker portal (usually `<publisher-prefix>_<name>`, e.g.
`p1_channelconfig` -> entity set `p1_channelconfigs`), and those may
not match the design doc's names exactly. Once the real table exists,
update the four *_ENTITY_SET / *_COLUMNS constants just below to match
what the maker portal actually generated -- nothing else in this file
should need to change.

AUTH: Dataverse's Web API needs an Azure AD app registration with
Dataverse API permissions (client-credentials / app-only flow, since
this runs unattended, not on behalf of a signed-in user). AZURE_CLIENT_ID
and AZURE_TENANT_ID are already in .env (reused from the Copilot Studio
setup), but that app registration was granted access to Copilot
Studio / Graph scopes, not necessarily Dataverse -- it may need its own
registration, or an additional API permission + admin consent, plus a
client secret, none of which exist yet. AZURE_CLIENT_SECRET and
DATAVERSE_URL are both new .env keys this script needs that aren't
there yet (see the __main__ guard below -- it checks for and names
exactly what's missing rather than failing opaquely).

Safe to run repeatedly, same guarantee as sync_to_supabase.py: it
reads Dataverse's current state fresh every run and only ever writes
the fields that actually differ from what's live in SQLite right now
(see _diff_channel below) -- update_channel_config() does not diff
internally (it writes + audits any field it's given, even unchanged),
so this script has to do that diffing itself before calling it, or
every run would spam the audit log with no-op "changes."

Usage:
    uv run python scripts/sync_from_dataverse.py
    uv run python scripts/sync_from_dataverse.py --dry-run   # prints the diff, writes nothing
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

import httpx
import msal

from p1.config.loader import ChannelConfigStore, DEFAULT_DB_PATH
from p1.config.schema import ExceptionEntry

# --- PLACEHOLDERS: fix these once the real table exists (see module docstring) ---
CHANNELCONFIG_ENTITY_SET = "p1_channelconfigs"
CHANNELCONFIG_COLUMNS = {
    "channel_id": "p1_channelid",
    "update_window_start": "p1_updatewindowstart",  # expected format: "HH:MM:SS"
    "update_window_end": "p1_updatewindowend",
}
CHANNELROSTER_ENTITY_SET = "p1_channelrosters"
CHANNELROSTER_COLUMNS = {
    "channel_id": "p1_channelid",
    "member_id": "p1_memberid",
}
CHANNELEXCEPTION_ENTITY_SET = "p1_channelexceptions"
CHANNELEXCEPTION_COLUMNS = {
    "channel_id": "p1_channelid",
    "member_id": "p1_memberid",
    "reason": "p1_reason",
}
# --- end placeholders ---

UPDATED_BY = "dataverse:sync_from_dataverse"


def _get_dataverse_token(dataverse_url: str) -> str:
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    client_secret = os.environ.get("AZURE_CLIENT_SECRET")
    missing = [
        name
        for name, val in [
            ("AZURE_TENANT_ID", tenant_id),
            ("AZURE_CLIENT_ID", client_id),
            ("AZURE_CLIENT_SECRET", client_secret),
        ]
        if not val
    ]
    if missing:
        raise RuntimeError(
            f"Missing from .env: {', '.join(missing)}. AZURE_CLIENT_SECRET in "
            "particular is new -- the existing app registration may also need "
            "Dataverse API permissions (with admin consent) added, separate "
            "from whatever scopes it already has for Copilot Studio/Graph."
        )
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )
    result = app.acquire_token_for_client(scopes=[f"{dataverse_url}/.default"])
    if "access_token" not in result:
        raise RuntimeError(
            f"Dataverse auth failed: {result.get('error_description', result)}"
        )
    return result["access_token"]


def _fetch(client: httpx.Client, dataverse_url: str, entity_set: str, select: list[str]) -> list[dict]:
    url = f"{dataverse_url}/api/data/v9.2/{entity_set}"
    params = {"$select": ",".join(select)}
    rows: list[dict] = []
    while url:
        resp = client.get(url, params=params if "?" not in url else None)
        resp.raise_for_status()
        body = resp.json()
        rows.extend(body.get("value", []))
        url = body.get("@odata.nextLink")
        params = None  # nextLink already carries its own query string
    return rows


def _fetch_dataverse_state(dataverse_url: str, token: str) -> dict[str, dict]:
    """Returns {channel_id: {"update_window_start": time, "update_window_end":
    time, "roster": [member_id, ...], "exceptions": [{"member_id", "reason"}, ...]}}
    for every channel Dataverse currently has an opinion about. A channel with
    no p1_channelconfig row is simply absent from this dict -- this script
    never invents a channel's window from roster/exception rows alone."""
    headers = {
        "Authorization": f"Bearer {token}",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
        "Accept": "application/json",
    }
    with httpx.Client(headers=headers, timeout=30.0) as client:
        config_rows = _fetch(
            client, dataverse_url, CHANNELCONFIG_ENTITY_SET, list(CHANNELCONFIG_COLUMNS.values())
        )
        roster_rows = _fetch(
            client, dataverse_url, CHANNELROSTER_ENTITY_SET, list(CHANNELROSTER_COLUMNS.values())
        )
        exception_rows = _fetch(
            client, dataverse_url, CHANNELEXCEPTION_ENTITY_SET, list(CHANNELEXCEPTION_COLUMNS.values())
        )

    state: dict[str, dict] = {}
    for row in config_rows:
        channel_id = row[CHANNELCONFIG_COLUMNS["channel_id"]]
        state[channel_id] = {
            "update_window_start": time.fromisoformat(row[CHANNELCONFIG_COLUMNS["update_window_start"]]),
            "update_window_end": time.fromisoformat(row[CHANNELCONFIG_COLUMNS["update_window_end"]]),
            "roster": [],
            "exceptions": [],
        }
    for row in roster_rows:
        channel_id = row[CHANNELROSTER_COLUMNS["channel_id"]]
        if channel_id in state:
            state[channel_id]["roster"].append(row[CHANNELROSTER_COLUMNS["member_id"]])
    for row in exception_rows:
        channel_id = row[CHANNELEXCEPTION_COLUMNS["channel_id"]]
        if channel_id in state:
            state[channel_id]["exceptions"].append(
                {
                    "member_id": row[CHANNELEXCEPTION_COLUMNS["member_id"]],
                    "reason": row[CHANNELEXCEPTION_COLUMNS["reason"]],
                }
            )
    return state


def _diff_channel(dataverse_channel: dict, current) -> dict:
    """Compares Dataverse's view of one channel against the live SQLite
    config (current = get_effective_config() result) and returns only the
    kwargs that actually differ -- this is the diffing
    update_channel_config() itself does not do (see module docstring).
    Roster and exceptions are compared order-independently so a Dataverse
    view/export that happens to list rows in a different order doesn't
    register as a change."""
    changed: dict = {}

    dv_roster = sorted(dataverse_channel["roster"])
    if dv_roster and dv_roster != sorted(current.roster):
        changed["roster"] = dataverse_channel["roster"]

    if dataverse_channel["update_window_start"] != current.update_window_start:
        changed["update_window_start"] = dataverse_channel["update_window_start"]
    if dataverse_channel["update_window_end"] != current.update_window_end:
        changed["update_window_end"] = dataverse_channel["update_window_end"]

    dv_exceptions_key = sorted(
        (e["member_id"], e["reason"]) for e in dataverse_channel["exceptions"]
    )
    current_exceptions_key = sorted((e.member_id, e.reason) for e in current.exceptions)
    if dv_exceptions_key != current_exceptions_key:
        changed["exceptions"] = [
            ExceptionEntry.model_validate(e) for e in dataverse_channel["exceptions"]
        ]

    return changed


def run_sync(*, dry_run: bool = False, db_path: str = str(DEFAULT_DB_PATH)) -> int:
    dataverse_url = os.environ.get("DATAVERSE_URL")
    if not dataverse_url:
        print(
            "DATAVERSE_URL must be set in .env (e.g. "
            "https://digitalt3.crm.dynamics.com) -- not there yet."
        )
        return 1

    token = _get_dataverse_token(dataverse_url.rstrip("/"))
    dataverse_state = _fetch_dataverse_state(dataverse_url.rstrip("/"), token)

    store = ChannelConfigStore()
    total_changed = 0
    for channel_id, dv_channel in dataverse_state.items():
        try:
            current = store.get_effective_config(channel_id, db_path=db_path)
        except KeyError:
            print(f"  {channel_id}: skipped -- no channel_config row in SQLite yet (sync_to_db() not run for it?)")
            continue

        changed = _diff_channel(dv_channel, current)
        if not changed:
            print(f"  {channel_id}: no changes")
            continue

        field_list = ", ".join(changed)
        if dry_run:
            print(f"  {channel_id}: WOULD update [{field_list}] (dry run -- nothing written)")
        else:
            store.update_channel_config(
                channel_id, updated_by=UPDATED_BY, db_path=db_path, **changed
            )
            print(f"  {channel_id}: updated [{field_list}]")
        total_changed += 1

    print(f"Done -- {total_changed} channel(s) with changes out of {len(dataverse_state)} checked.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Print the diff, write nothing")
    args = parser.parse_args()
    return run_sync(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
