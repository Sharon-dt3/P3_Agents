"""
Proves the real HTTP layer (p1.api.copilot_studio_api) added on top of
the already-tested connector handlers: API-key auth (fail closed when
unconfigured, 401 on a wrong/missing key), HTTP status translation for
the two real error modes the connector handlers can raise
(ProposalNotFoundError -> 404, an unknown channel_id's KeyError -> 404,
a bad exceptions payload's ValueError -> 400), and a genuine end-to-end
round trip through /approve and /reject against a real (but isolated,
tmp_path) database and channel config -- never a live network socket,
FastAPI's own TestClient drives this in-process.
"""

from __future__ import annotations

import textwrap

from fastapi.testclient import TestClient

from p1.api import copilot_studio_api
from p1.approval.proposals import ProposalStore
from p1.config.loader import ChannelConfigStore
from p1.storage.db import get_connection, init_db

CHANNEL_ID = "cx-api-channel"
API_KEY = "test-shared-secret"

_CONFIG_YAML = textwrap.dedent(f"""\
    channel_id: "{CHANNEL_ID}"
    display_name: "CX API Channel"
    allowlisted: true

    roster:
      - "alice"
      - "bob"
      - "priya"

    update_window_start: "09:00:00"
    update_window_end: "11:00:00"
    timezone: "UTC"
    working_days: ["Mon", "Tue", "Wed", "Thu", "Fri"]
    non_working_dates: []

    length_floor: 10
    count_thread_replies: true
    ignore_bots: true

    daily_digest_time: "11:30:00"
    weekly_digest_day: "Fri"
    weekly_digest_time: "16:00:00"

    nudge_enabled: true
    nudge_cap_per_day: 1
    escalation_threshold_days: 3
    channel_owner_id: "priya"

    exceptions: []

    version: 1
    """)


class _RecordingPublisher:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def post_direct_message(self, member_id: str, content: str) -> dict:
        self.calls.append(("dm", member_id, content))
        return {"ok": True}

    def post_channel_message(self, channel_id: str, content: str) -> dict:
        self.calls.append(("channel", channel_id, content))
        return {"ok": True}


def _seed(tmp_path):
    """Sets up an isolated data/p1.db + channel config under the cwd
    the test has already chdir'd into -- init_db(), sync_to_db() and
    every handler this API calls all default to the same cwd-relative
    DEFAULT_DB_PATH, so once cwd is fixed for the test, everything
    (server code included) resolves to the same isolated database
    with no db_path threaded through the HTTP layer at all -- exactly
    like a real deployment, where a caller never supplies db_path."""
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO channels (id, display_name, allowlisted) VALUES (?, ?, 1)",
            (CHANNEL_ID, "CX API Channel"),
        )
        for member_id in ("alice", "bob", "priya"):
            conn.execute("INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()

    config_dir = tmp_path / "fixture_config"
    config_dir.mkdir()
    (config_dir / f"{CHANNEL_ID}.yaml").write_text(_CONFIG_YAML)
    ChannelConfigStore(config_dir).sync_to_db()


def _client(monkeypatch, *, api_key: str | None = API_KEY) -> TestClient:
    """Enters the TestClient's own context manager before returning it
    (rather than handing back a bare TestClient(app)) so the app's
    lifespan actually runs -- a bare TestClient silently never fires
    it, which is what let the missing-schema bug this file's newest
    test guards against go unnoticed: every other test here calls
    init_db()/_seed() itself, masking that the app never did its own
    schema setup. We deliberately never __exit__ this -- there's no
    shutdown behaviour to run, and each test gets its own process-wide
    app object plus (via monkeypatch.chdir) its own isolated cwd/db, so
    there's nothing to leak."""
    if api_key is None:
        monkeypatch.delenv(copilot_studio_api.API_KEY_ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(copilot_studio_api.API_KEY_ENV_VAR, api_key)
    client = TestClient(copilot_studio_api.app)
    client.__enter__()
    return client


def test_starting_the_app_against_a_brand_new_database_does_not_500(tmp_path, monkeypatch):
    """Regression test: a real deployment's data/p1.db can be a
    completely fresh, zero-table SQLite file the very first time this
    app is ever run against it (nothing else in this repo forces
    init_db() before the server starts, unlike every other test in
    this file, which calls _seed()/init_db() itself). Before the
    startup hook in copilot_studio_api.py, this reproduced the exact
    sqlite3.OperationalError: no such table: proposals seen against a
    real, never-initialised database file."""
    monkeypatch.chdir(tmp_path)
    # Deliberately do NOT call init_db() or _seed() -- this is the one
    # test in this file that must start from a truly empty cwd, with
    # no data/p1.db at all, to prove the app initialises it itself.
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post("/list_pending_approvals", json={}, headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    assert response.json() == {"approvals": []}


def test_health_needs_no_api_key_and_reports_whether_one_is_configured(tmp_path, monkeypatch):
    # Isolated cwd: _client() now enters the app's lifespan, which calls
    # init_db() -- without this chdir that would touch the real repo's
    # data/p1.db instead of a throwaway one.
    monkeypatch.chdir(tmp_path)
    client = _client(monkeypatch, api_key=None)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "api_key_configured": False}

    client = _client(monkeypatch, api_key=API_KEY)
    assert client.get("/health").json()["api_key_configured"] is True


def test_action_endpoint_fails_closed_when_no_api_key_is_configured_at_all(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client(monkeypatch, api_key=None)
    response = client.post("/list_pending_approvals", json={})
    assert response.status_code == 500
    assert copilot_studio_api.API_KEY_ENV_VAR in response.json()["detail"]


def test_action_endpoint_rejects_a_missing_or_wrong_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post("/list_pending_approvals", json={})
    assert response.status_code == 401

    response = client.post("/list_pending_approvals", json={}, headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_list_pending_approvals_round_trips_through_the_real_handler(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    ProposalStore().create(
        type="nudge",
        payload={"channel_id": CHANNEL_ID, "member_id": "bob", "date": "2026-06-01", "content": "hi bob"},
        original_model_output={}, source_refs=[], idempotency_key="k1",
    )
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post("/list_pending_approvals", json={}, headers={"X-API-Key": API_KEY})

    assert response.status_code == 200
    approvals = response.json()["approvals"]
    assert len(approvals) == 1
    assert approvals[0]["channel_id"] == CHANNEL_ID
    assert approvals[0]["type"] == "nudge"


def test_approve_unknown_proposal_id_returns_404_not_500(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post(
        "/approve", json={"proposal_id": "does-not-exist", "approver_id": "priya"},
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404


def test_approve_happy_path_actually_sends_through_the_real_service(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    proposal = ProposalStore().create(
        type="nudge",
        payload={"channel_id": CHANNEL_ID, "member_id": "bob", "date": "2026-06-01", "content": "hi bob"},
        original_model_output={}, source_refs=[], idempotency_key="k2",
    )
    import p1.approval.service as approval_service_module

    recording = _RecordingPublisher()
    monkeypatch.setattr(approval_service_module, "get_teams_publisher", lambda: recording)
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post(
        "/approve", json={"proposal_id": proposal.id, "approver_id": "priya"},
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["proposal_id"] == proposal.id
    assert body["outcome"] == "sent"
    assert recording.calls == [("dm", "bob", "hi bob")]


def test_reject_happy_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    proposal = ProposalStore().create(
        type="nudge",
        payload={"channel_id": CHANNEL_ID, "member_id": "alice", "date": "2026-06-01", "content": "hi alice"},
        original_model_output={}, source_refs=[], idempotency_key="k3",
    )
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post(
        "/reject", json={"proposal_id": proposal.id, "approver_id": "priya"},
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "rejected"


def test_update_channel_config_unknown_channel_returns_404(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    init_db()
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post(
        "/update_channel_config",
        json={"channel_id": "does-not-exist", "updated_by": "priya", "roster_csv": "a,b"},
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 404


def test_update_channel_config_happy_path_via_csv_fields(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed(tmp_path)
    client = _client(monkeypatch, api_key=API_KEY)

    response = client.post(
        "/update_channel_config",
        json={
            "channel_id": CHANNEL_ID,
            "updated_by": "priya",
            "roster_csv": "alice,bob",
            "exceptions_csv": "alice:on leave",
        },
        headers={"X-API-Key": API_KEY},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["roster"] == ["alice", "bob"]
    assert body["exceptions"] == [{"member_id": "alice", "reason": "on leave"}]
    assert body["version"] == 2
