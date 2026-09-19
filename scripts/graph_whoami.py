"""
Read-only diagnostic: prints the real identity fields Microsoft Graph
returns for the signed-in account (via GET /me), using the same
GRAPH_ACCESS_TOKEN scripts/graph_login.py already writes to .env.

Why this exists: GraphTeamsReader._parse_message() sets a message's
author_id from from.user.id -- the Azure AD OBJECT ID (a GUID) -- not
an email/UPN string. Every channel config's roster (e.g.
config/channels/p1-agent-test.yaml's "SharonS@digitalt3.com") was
written as an email, matching the mock reader's fixture convention,
because GraphTeamsReader had never been exercised against a live
tenant until this week -- so no real message has ever needed to match
a real roster entry before. This script exists purely to surface the
real GUID a real human message will actually carry, so that mismatch
can be fixed with a real value instead of a guess. See DECISION_LOG.md.

Usage:
    uv run python scripts/graph_whoami.py
"""

from __future__ import annotations

import os

import httpx
from dotenv import load_dotenv

load_dotenv()


def _default_http_get(access_token: str) -> httpx.Response:
    return httpx.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15.0,
    )


def run_whoami(*, access_token: str, http_get=_default_http_get) -> int:
    """http_get is a seam for tests: production calls the real Graph
    /me endpoint, tests substitute a fake httpx.Response and never
    touch a real network or tenant."""
    resp = http_get(access_token)
    resp.raise_for_status()
    data = resp.json()

    print(f"id (AAD object id -- what author_id will actually be on your real messages): {data.get('id')}")
    print(f"userPrincipalName: {data.get('userPrincipalName')}")
    print(f"displayName: {data.get('displayName')}")
    print(f"mail: {data.get('mail')}")
    return 0


def main() -> int:
    access_token = os.environ.get("GRAPH_ACCESS_TOKEN")
    if not access_token:
        print("GRAPH_ACCESS_TOKEN must be set in .env -- run scripts/graph_login.py first.")
        return 1

    return run_whoami(access_token=access_token)


if __name__ == "__main__":
    raise SystemExit(main())
