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

API_KEY_ENV_VAR = "COPILOT_STUDIO_API_KEY"

app = FastAPI(
    title="P1 Channel -- Copilot Studio connector backend",
    description=(
        "Real HTTP surface over p1.adapters.copilot_studio_connector "
        "(CHN-25). Import /openapi.json as a Power Platform custom "
        "connector's swagger definition."
    ),
    version="1.0.0",
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
    return {"status": "ok", "api_key_configured": bool(os.environ.get(API_KEY_ENV_VAR))}


@app.post("/list_pending_approvals")
def list_pending_approvals(_: None = Depends(require_api_key)) -> dict:
    return handle_list_pending_approvals({})


@app.post("/approve")
def approve(body: ApproveRequest, _: None = Depends(require_api_key)) -> dict:
    try:
        return handle_approve(body.model_dump())
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/reject")
def reject(body: RejectRequest, _: None = Depends(require_api_key)) -> dict:
    try:
        return handle_reject(body.model_dump())
    except ProposalNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/update_channel_config")
def update_channel_config(body: UpdateChannelConfigRequest, _: None = Depends(require_api_key)) -> dict:
    try:
        return handle_update_channel_config(body.model_dump(exclude_none=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
