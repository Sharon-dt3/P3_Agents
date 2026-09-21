"""
One-time interactive sign-in that seeds the persisted Graph token cache
p1.adapters.graph_auth reads from -- run this once before starting
scripts/live_runner_p1_agent_test.py for the first time (the live
runner will also trigger this same interactive flow itself on its very
first startup if the cache doesn't exist yet, so running this ahead of
time is a convenience, not a strict requirement).

Requires AZURE_TENANT_ID and AZURE_CLIENT_ID in .env, same as
scripts/graph_login.py. Unlike graph_login.py, this does NOT write
GRAPH_ACCESS_TOKEN into .env -- that variable is for the older,
manual-rerun scripts (run_live_pipeline_p1_agent_test.py and friends);
this seeds the separate on-disk cache the live runner's own silent
refresh reads from instead.

Usage:
    uv run python scripts/graph_seed_token_cache.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "packages" / "spine" / "src"))

from dotenv import load_dotenv

load_dotenv()

from p1.adapters.graph_auth import GraphAuthError, get_access_token


def main() -> int:
    tenant_id = os.environ.get("AZURE_TENANT_ID")
    client_id = os.environ.get("AZURE_CLIENT_ID")
    if not tenant_id or not client_id:
        print("AZURE_TENANT_ID and AZURE_CLIENT_ID must both be set in .env (see .env.example).")
        return 1

    try:
        get_access_token(tenant_id=tenant_id, client_id=client_id, allow_interactive=True)
    except GraphAuthError as exc:
        print(f"Sign-in failed: {exc}")
        return 1

    print("Signed in. Token cache seeded -- scripts/live_runner_p1_agent_test.py can now refresh silently.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
