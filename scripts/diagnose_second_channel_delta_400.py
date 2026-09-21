"""
One-off diagnostic (not part of the app) for tonight's 400 Bad Request on
Teams-agent-test's very first ingest tick.

What it does: calls Graph's delta endpoint exactly like GraphTeamsReader
does for page 1 (relative URL), then -- if Graph hands back a
@odata.nextLink -- calls that exact URL for page 2, but WITHOUT calling
raise_for_status() blindly. Instead it prints the full response body on
any non-2xx, because httpx's own HTTPStatusError message only ever says
"400 Bad Request for url ..." and throws away Graph's actual error.code /
error.message, which is the one thing that would tell us what's really
wrong instead of guessing.

Run this from the real project root, in the real venv:
    uv run python scripts/diagnose_second_channel_delta_400.py
(or: source .venv/bin/activate && python scripts/diagnose_second_channel_delta_400.py)

Safe to run any number of times -- it only does GET requests, and reuses
the existing cached Graph token (no new sign-in unless the cache is dead).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

import httpx
from dotenv import load_dotenv

load_dotenv()

from p1.adapters.graph_auth import get_access_token  # noqa: E402

TEAM_ID = os.environ["GRAPH_TEAM_ID"]
CHANNEL_ID = "19:ID3C8qqqxb40IRhNJ3xvts2BWAgRac3SxYwm9XyBEGM1@thread.tacv2"  # Teams-agent-test
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def show(label: str, resp: httpx.Response) -> None:
    print(f"\n--- {label} ---")
    print(f"status: {resp.status_code}")
    print(f"request url: {resp.request.url}")
    try:
        body = resp.json()
        print("body:")
        print(json.dumps(body, indent=2)[:3000])
    except Exception:
        print("body (non-JSON, first 2000 chars):")
        print(resp.text[:2000])


def main() -> None:
    token = get_access_token(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        allow_interactive=True,
    )
    client = httpx.Client(
        base_url=GRAPH_BASE_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )

    page1_url = f"/teams/{TEAM_ID}/channels/{CHANNEL_ID}/messages/delta"
    resp1 = client.get(page1_url)
    show("page 1 (relative URL)", resp1)

    if resp1.status_code != 200:
        print("\nPage 1 itself failed -- stopping here, that's the real problem.")
        return

    data1 = resp1.json()
    next_link = data1.get("@odata.nextLink")
    delta_link = data1.get("@odata.deltaLink")
    print(f"\n@odata.nextLink present: {next_link is not None}")
    print(f"@odata.deltaLink present: {delta_link is not None}")

    if not next_link:
        print("\nNo nextLink returned -- page 1 was the only/last page. "
              "That means tonight's 400 did NOT come from following this "
              "page's own nextLink with an unmodified GET -- something else "
              "changed the token or the URL before the second request went out.")
        return

    # Exactly what GraphTeamsReader.list_messages() does: pass the
    # absolute nextLink straight to client.get(), unmodified.
    resp2 = client.get(next_link)
    show("page 2 (following @odata.nextLink verbatim)", resp2)


if __name__ == "__main__":
    main()
