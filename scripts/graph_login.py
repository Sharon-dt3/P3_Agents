"""
Device-code sign-in helper for Microsoft Graph (CHN-01's own "next step",
finally built): mints a real, short-lived delegated access token by having
a real human sign in through Microsoft's own login page, never a
fabricated or simulated credential.

Requires AZURE_TENANT_ID and AZURE_CLIENT_ID in the environment (see
.env.example -- AZURE_CLIENT_ID is already the registered
p1-teams-intelligence app, 1e9e359c-8cd0-4554-9cfd-552d837bd7a8, per
DECISION_LOG.md's CHN-01 entry). No client secret is needed or used --
a device-code flow is Microsoft's own public-client (no-secret) login
mechanism, built for exactly this kind of script, which is why the
app registration's "Allow public client flows" setting must be turned
on (see that same DECISION_LOG entry).

Usage:
    uv run python scripts/graph_login.py

Prints a short code and a URL. Open that URL in any browser, sign in
with an account that is a member of the channels P1 will read (CHN-01's
Option A), and enter the code. Once that sign-in completes, this script
writes the resulting access token into .env's GRAPH_ACCESS_TOKEN line
(creating that line if it isn't already there -- every other line is
left untouched) and prints how long it's valid for, typically about an
hour.

Nothing here can succeed before tenant admin consent has actually been
granted for the scopes below -- Microsoft will refuse the sign-in with an
AADSTS65001 "needs admin approval" style error if either hasn't been (see
DECISION_LOG.md's CHN-01 entry for where that stands). ChannelMessage.Read.All
was the original CHN-01 grant; Channel.ReadBasic.All was added once
GraphTeamsReader's list_channels() turned out to need its own, narrower
permission (needed by the ingestion sync and the scope-gate's allowlist
filtering). A third permission, ChannelMember.Read.All, is configured on
the app registration but deliberately NOT requested here -- it's blocked on
admin consent (only Alfred can grant it) and nothing live needs it yet,
since list_channel_members() is written and tested against the mock but
not wired into any real code path. Add it back to GRAPH_SCOPES once both
are true: consent lands, and something live actually calls it -- see that
same entry's follow-up note.

This access token is short-lived by design -- re-run this script
whenever it expires. Turning this into something that refreshes itself
automatically without a human in the loop is a separate future step,
deliberately not attempted here (see this row's own DECISION_LOG entry
for why).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import msal
from dotenv import load_dotenv

load_dotenv()

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
GRAPH_SCOPES = [
    "ChannelMessage.Read.All",  # list_messages -- reading channel content
    "Channel.ReadBasic.All",  # list_channels -- ingestion sync + scope-gate allowlist filtering
    # "ChannelMember.Read.All" is configured on the app registration but not
    # requested here yet -- blocked on admin consent and unused by any live
    # code path (see DECISION_LOG.md CHN-01 follow-up).
]


class DeviceFlowError(Exception):
    """Raised when MSAL can't start or complete the device-code flow --
    e.g. missing config, or Microsoft rejects the sign-in (often because
    admin consent is still pending, or the app isn't set up as a public
    client). Never caught and silently swallowed -- main() reports it
    and exits non-zero."""


def acquire_token(
    *,
    tenant_id: str,
    client_id: str,
    app_factory=msal.PublicClientApplication,
) -> dict:
    """Runs the device-code flow and returns MSAL's token result dict.

    app_factory is a seam for tests: production always calls the real
    msal.PublicClientApplication (the default), tests substitute a fake
    one, so no real network call, and no real interactive login, ever
    happens under pytest -- the same "written, tested against a fake,
    never run live under test" discipline as GraphTeamsReader and
    PowerAutomateTeamsPublisher.
    """
    app = app_factory(client_id, authority=f"https://login.microsoftonline.com/{tenant_id}")
    flow = app.initiate_device_flow(scopes=GRAPH_SCOPES)
    if "user_code" not in flow:
        raise DeviceFlowError(f"Could not start device flow: {flow.get('error_description', flow)}")
    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise DeviceFlowError(
            f"Sign-in did not produce a token: {result.get('error')} -- "
            f"{result.get('error_description')}"
        )
    return result


def write_token_to_env(access_token: str, *, env_path: Path = ENV_PATH) -> None:
    """Replaces (or appends) only the GRAPH_ACCESS_TOKEN line in .env,
    leaving every other line -- including AZURE_TENANT_ID, the
    Anthropic key, and everything else -- byte-identical."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    new_line = f"GRAPH_ACCESS_TOKEN={access_token}"
    for i, line in enumerate(lines):
        if line.startswith("GRAPH_ACCESS_TOKEN="):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    env_path.write_text("\n".join(lines) + "\n")


def main() -> int:
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if not tenant_id or not client_id:
        print("AZURE_TENANT_ID and AZURE_CLIENT_ID must both be set in .env (see .env.example).")
        return 1

    try:
        result = acquire_token(tenant_id=tenant_id, client_id=client_id)
    except DeviceFlowError as exc:
        print(f"Sign-in failed: {exc}")
        return 1

    write_token_to_env(result["access_token"], env_path=ENV_PATH)
    expires_in_minutes = result.get("expires_in", 0) // 60
    print(f"Signed in. Access token written to .env's GRAPH_ACCESS_TOKEN (valid for about {expires_in_minutes} minutes).")
    print("Next: set GRAPH_TEAM_ID in .env (from a channel's \"Get link to channel\" URL) and TEAMS_READER_MODE=graph, then run scripts/graph_smoke_test.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
