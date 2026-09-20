"""
CHN-25, taken one real step further: an actual, internet-hostable HTTP
API in front of the already-real, already-tested connector handlers
(p1.adapters.copilot_studio_connector). This is the piece that was
missing for "Copilot Studio + Dataverse" to ever be more than a
documented contract -- a custom connector in Power Platform needs a
real URL and a real OpenAPI/Swagger document to import, and nothing in
this repo was reachable over HTTP at all before this file.

What this changes, and what it doesn't:
- Every handler this app calls (handle_list_pending_approvals,
  handle_approve, handle_reject, handle_update_channel_config) is
  UNCHANGED -- this is a thin adapter from HTTP request/response to
  the exact same request/response dict shape
  docs/copilot_studio/connector_contract.md already documents and
  tests/unit/test_copilot_studio_connector.py already proves. There is
  still no branch anywhere that behaves differently for this surface
  than for the Streamlit fallback or a hypothetical connector caller.
- This does NOT create a Copilot Studio agent or a Dataverse table --
  those still require a human in the Power Platform maker portal, with
  real tenant access. What this DOES create is the one thing a human
  in that portal would need: a running server whose FastAPI-generated
  /openapi.json a custom connector can import directly, and a real
  endpoint to point it at once that server is reachable from Microsoft's
  cloud (which still requires a hosting decision -- see README).

Auth: every action endpoint (not /health) requires a static API key in
the `X-API-Key` header, checked against COPILOT_STUDIO_API_KEY (.env).
This is a deliberate, disclosed scope cut, not a real per-user identity
check -- see this row's own DECISION_LOG entry for why: there is no
live Teams/Entra identity for this app to bind approver_id/updated_by
to yet (same gap connector_contract.md already names), so a shared key
is what stands between "anyone who can reach this URL" and "only Power
Platform, holding a secret only it and this server know" until a real
identity binding is built. If COPILOT_STUDIO_API_KEY is unset, this
app refuses to start at all (fail closed, never fail open) -- see
_require_api_key_configured below.

Run with: uv run uvicorn p1.api.copilot_studio_api:app --reload
(or `make copilot-api`). Never imports or starts anything from a test
context -- tests/unit/test_copilot_studio_api.py drives this app
in-process via FastAPI's own TestClient, no real network socket ever
opens under pytest.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

load_dotenv()

from p1.adapters.copilot_studio_connector import (
    handle_approve,
    handle_list_pending_approvals,
    handle_reject,
    handle_update_channel_config,
)
from p1.approval.proposals import ProposalNotFoundError
from p1.storage.db import DEFAULT_DB_PATH, init_db

API_KEY_ENV_VAR = "COPILOT_STUDIO_API_KEY"
DB_PATH_ENV_VAR = "P1_DB_PATH"


def _db_path() -> Path:
    """2026-09-20: every handle_* call below used to run with NO db_path
    at all, which silently fell back to each handler's own default
    parameter (DEFAULT_DB_PATH = "data/p1.db") -- a fresh,
    essentially-empty test database, completely separate from
    data/p1_live.db, the one scripts/live_runner_p1_agent_test.py
    actually ingests into and publishes from. Confirmed live:
    list_pending_approvals returned {"approvals":[]} and
    update_channel_config 404'd on a channel_id that genuinely has a
    synced config -- both because this API was reading the wrong file,
    not because either was actually empty/missing. This module's own
    docstring already anticipated "any DB_PATH a real deployer points
    this at)" -- that env var just never existed until now.

    2026-09-20, same day: this used to be a module-level constant
    computed once at import time, which is exactly the mistake
    DECISION_LOG.md's frozen-config entry for the live runner already
    named elsewhere -- tests/unit/test_copilot_studio_api.py's own
    _seed() seeds an isolated per-test database assuming DEFAULT_DB_PATH,
    and a frozen DB_PATH read once at import time can never be
    overridden per test via monkeypatch, so every action endpoint
    silently read a different file than the one the test just seeded.
    Reading the env var fresh here, at request/startup time, is what
    lets tests (and a real deployer changing .env and restarting) get
    the value they actually asked for. See DECISION_LOG.md.
    """
    return Path(os.environ.get(DB_PATH_ENV_VAR, str(DEFAULT_DB_PATH)))


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """A fresh deployment's data/p1.db (or any DB_PATH a real deployer
    points this at) may not have a single migration applied yet --
    unlike every test in tests/unit/test_copilot_studio_api.py, which
    always calls init_db() itself before hitting this app, nothing
    forced that for a real `uvicorn`/`make copilot-api` run before this
    hook existed. Without it, every action endpoint 500s with
    sqlite3.OperationalError: no such table: proposals (or messages,
    or channels...) the first time it's ever queried against a
    brand-new or half-provisioned database file -- run_migrations()
    is idempotent (tracked via schema_migrations), so this is always
    safe to call on every startup, not just the first. FastAPI's
    TestClient only runs this when used as a context manager (see
    _client() below) -- a bare TestClient(app) silently skips the
    whole ASGI lifespan, startup included.
    """
    init_db(_db_path())
    yield


app = FastAPI(
    title="P1 Channel -- Copilot Studio connector backend",
    description=(
        "Real HTTP surface over p1.adapters.copilot_studio_connector "
        "(CHN-25). Import /openapi.json as a Power Platform custom "
        "connector's swagger definition."
    ),
    version="1.0.0",
    lifespan=_lifespan,
)


def _require_api_key_configured() -> str:
    """Fail closed: refuses every action request rather than starting
    up "open" if no key has been configured at all. Distinct from a
    wrong/missing key on a given request, which is a 401, not a 500."""
    configured = os.environ.get(API_KEY_ENV_VAR)
    if not configured:
        raise HTTPException(
            status_code=500,
            detail=f"{API_KEY_ENV_VAR} is not set -- refusing to serve any action endpoint until it is.",
        )
    return configured


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    configured = _require_api_key_configured()
    if x_api_key != configured:
        raise HTTPException(status_code=401, detail="Missing or incorrect X-API-Key header.")


class ApproveRequest(BaseModel):
    proposal_id: str
    approver_id: str


class RejectRequest(BaseModel):
    proposal_id: str
    approver_id: str


class UpdateChannelConfigRequest(BaseModel):
    channel_id: str
    updated_by: str
    roster: list[str] | None = None
    roster_csv: str | None = None
    update_window_start: str | None = None
    update_window_end: str | None = None
    exceptions: list[dict] | None = None
    exceptions_csv: str | None = None


@app.get("/health")
def health() -> dict:
    """No auth required -- a connectivity/health probe only, never a
    capability endpoint. Returns whether an API key is even configured
    (not its value), so a deployer can tell "not reachable" apart from
    "reachable but not configured" without guessing."""
    return {
        "status": "ok",
        "api_key_configured": bool(os.environ.get(API_KEY_ENV_VAR)),
        "db_path": str(_db_path()),
    }


@app.post("/list_pending_approvals")
def list_pending_approvals(_: None = Depends(require_api_key)) -> dict:
    return handle_list_pending_approvals({}, db_path=_db_path())


@app.post("/approve")
def approve(body: ApproveRequest, _: None = Depends(require_api_key)) -> dict:
    try:
        return handle_approve(body.model_dump(), db_path=_db_path())
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/reject")
def reject(body: RejectRequest, _: None = Depends(require_api_key)) -> dict:
    try:
        return handle_reject(body.model_dump(), db_path=_db_path())
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/update_channel_config")
def update_channel_config(body: UpdateChannelConfigRequest, _: None = Depends(require_api_key)) -> dict:
    try:
        return handle_update_channel_config(body.model_dump(exclude_none=True), db_path=_db_path())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
