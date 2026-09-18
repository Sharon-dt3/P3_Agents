"""
CHN-25: app/approval_dashboard.py driven headlessly via
streamlit.testing.v1.AppTest -- proof that the Streamlit fallback
surface ITSELF works end to end (the actual widgets, not just the
p1.approval.service functions underneath it, already covered by
test_approval_service.py and test_copilot_studio_connector.py). This
is "the real, tested code" this row's own fallback requirement asks
for, exercised the same way a channel owner would actually click
through it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from p1.adapters.teams_reader import TeamsMessage
from p1.config.schema import ChannelConfig
from p1.nudges.nudge_job import run_nudge_job
from p1.storage.classifications_repo import ClassificationStore
from p1.storage.db import get_connection, init_db
from p1.storage.messages_repo import MessageStore

APP_PATH = str(Path(__file__).resolve().parents[2] / "app" / "approval_dashboard.py")
CHANNEL_ID = "app-channel"
MON = date(2026, 6, 1)


class _RecordingPublisher:
    def post_direct_message(self, member_id, content):
        return {"ok": True}

    def post_channel_message(self, channel_id, content):
        return {"ok": True}


def _config() -> ChannelConfig:
    from datetime import time

    return ChannelConfig(
        channel_id=CHANNEL_ID, display_name="App Channel", roster=["alice", "bob"],
        update_window_start=time(9, 0), update_window_end=time(11, 0), timezone="UTC",
        working_days=["Mon", "Tue", "Wed", "Thu", "Fri"], daily_digest_time=time(9, 0),
        weekly_digest_day="Fri", weekly_digest_time=time(16, 0), channel_owner_id="priya",
        nudge_enabled=True, nudge_cap_per_day=1,
    )


def _seed(db_path) -> None:
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute("INSERT INTO channels (id, display_name, allowlisted) VALUES (?, 'App Channel', 1)", (CHANNEL_ID,))
        for member_id in ("alice", "bob", "priya"):
            conn.execute("INSERT OR IGNORE INTO members (id, display_name) VALUES (?, ?)", (member_id, member_id))
        conn.commit()
    finally:
        conn.close()
    MessageStore(db_path).upsert_messages(
        [TeamsMessage(id="alice-mon", channel_id=CHANNEL_ID, author_id="alice",
                      posted_at=f"{MON.isoformat()}T09:30:00+00:00", body="text")]
    )
    ClassificationStore(db_path).record(message_id="alice-mon", label="update", method="model", confidence=0.9)


def _sync_config(db_path, config: ChannelConfig) -> None:
    import json

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO channel_config (
                channel_id, roster, update_window_start, update_window_end, timezone,
                working_days, non_working_dates, length_floor, count_thread_replies, ignore_bots,
                daily_digest_time, weekly_digest_day, weekly_digest_time, nudge_enabled,
                nudge_cap_per_day, escalation_threshold_days, channel_owner_id, exceptions, version
            ) VALUES (:channel_id, :roster, :update_window_start, :update_window_end, :timezone,
                :working_days, :non_working_dates, :length_floor, :count_thread_replies, :ignore_bots,
                :daily_digest_time, :weekly_digest_day, :weekly_digest_time, :nudge_enabled,
                :nudge_cap_per_day, :escalation_threshold_days, :channel_owner_id, :exceptions, :version)
            """,
            {
                "channel_id": config.channel_id, "roster": json.dumps(config.roster),
                "update_window_start": config.update_window_start.isoformat(),
                "update_window_end": config.update_window_end.isoformat(), "timezone": config.timezone,
                "working_days": json.dumps(config.working_days),
                "non_working_dates": json.dumps([d.isoformat() for d in config.non_working_dates]),
                "length_floor": config.length_floor, "count_thread_replies": int(config.count_thread_replies),
                "ignore_bots": int(config.ignore_bots), "daily_digest_time": config.daily_digest_time.isoformat(),
                "weekly_digest_day": config.weekly_digest_day, "weekly_digest_time": config.weekly_digest_time.isoformat(),
                "nudge_enabled": int(config.nudge_enabled), "nudge_cap_per_day": config.nudge_cap_per_day,
                "escalation_threshold_days": config.escalation_threshold_days,
                "channel_owner_id": config.channel_owner_id,
                "exceptions": json.dumps([e.model_dump() for e in config.exceptions]), "version": config.version,
            },
        )
        conn.commit()
    finally:
        conn.close()


def test_dashboard_lists_and_approves_a_pending_nudge(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    _sync_config(db_path, _config())
    run_nudge_job(CHANNEL_ID, _config(), _RecordingPublisher(), day=MON, db_path=db_path)

    monkeypatch.setenv("P1_DB_PATH", str(db_path))
    monkeypatch.setenv("P1_APPROVER_ID", "priya")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception

    body_text = " ".join(t.value for t in at.markdown) + " ".join(t.value for t in at.caption)
    assert "bob" in body_text

    approve_button = at.get_by_key("approve_" + next(iter(_pending_ids(db_path))))
    approve_button.click().run()
    assert not at.exception

    success_messages = [s.value for s in at.success]
    assert any("sent" in msg for msg in success_messages)

    conn = get_connection(db_path)
    try:
        status = conn.execute("SELECT status FROM proposals").fetchone()["status"]
    finally:
        conn.close()
    assert status == "applied"


def test_dashboard_saves_a_config_change(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    _seed(db_path)
    _sync_config(db_path, _config())

    monkeypatch.setenv("P1_DB_PATH", str(db_path))
    monkeypatch.setenv("P1_APPROVER_ID", "priya")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    assert not at.exception

    at.text_area[0].set_value("alice\nbob\ncarol").run()
    assert not at.exception
    at.button[-1].click().run()
    assert not at.exception

    success_messages = [s.value for s in at.success]
    assert any("Saved" in msg for msg in success_messages)

    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT roster, version FROM channel_config WHERE channel_id = ?", (CHANNEL_ID,)).fetchone()
        audit_count = conn.execute(
            "SELECT COUNT(*) AS n FROM audit WHERE entity_id = ? AND action = 'channel_config.updated'", (CHANNEL_ID,)
        ).fetchone()["n"]
    finally:
        conn.close()
    import json
    assert json.loads(row["roster"]) == ["alice", "bob", "carol"]
    assert row["version"] == 2
    assert audit_count == 1


def _pending_ids(db_path) -> list[str]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT id FROM proposals WHERE status = 'pending'").fetchall()
    finally:
        conn.close()
    return [r["id"] for r in rows]
