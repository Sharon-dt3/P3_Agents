import json
from pathlib import Path

import pytest
import yaml

from p1.config.loader import ChannelConfigStore
from p1.storage.db import get_connection, run_migrations

ALPHA = {
    "channel_id": "chn-alpha", "display_name": "Project Alpha", "allowlisted": True,
    "roster": ["priya", "james", "wei"],
    "update_window_start": "09:00:00", "update_window_end": "11:00:00",
    "timezone": "Asia/Colombo", "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "daily_digest_time": "11:30:00", "weekly_digest_day": "Fri", "weekly_digest_time": "16:00:00",
    "channel_owner_id": "priya",
}

BETA = {
    "channel_id": "chn-beta", "display_name": "Project Beta", "allowlisted": True,
    "roster": ["james", "wei", "diego"],
    "update_window_start": "08:00:00", "update_window_end": "10:00:00",
    "timezone": "America/New_York", "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "daily_digest_time": "10:30:00", "weekly_digest_day": "Thu", "weekly_digest_time": "15:00:00",
    "channel_owner_id": "diego", "nudge_enabled": True, "escalation_threshold_days": 2,
}


def _write_config(config_dir: Path, data: dict) -> None:
    (config_dir / f"{data['channel_id']}.yaml").write_text(yaml.safe_dump(data))


def test_loads_distinct_configs_for_two_channels(tmp_path):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, ALPHA)
    _write_config(config_dir, BETA)

    store = ChannelConfigStore(config_dir)
    configs = store.list_configured_channels()

    assert {c.channel_id for c in configs} == {"chn-alpha", "chn-beta"}
    alpha = store.get_channel_config("chn-alpha")
    beta = store.get_channel_config("chn-beta")
    assert alpha.roster != beta.roster
    assert alpha.timezone != beta.timezone
    assert alpha.update_window_start != beta.update_window_start


def test_roster_change_takes_effect_with_no_code_change(tmp_path):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, ALPHA)

    store = ChannelConfigStore(config_dir)
    before = store.get_channel_config("chn-alpha").roster

    edited = dict(ALPHA, roster=["priya", "james"])  # someone left the roster
    _write_config(config_dir, edited)

    after = store.get_channel_config("chn-alpha").roster

    assert before != after
    assert after == ["priya", "james"]


def test_invalid_config_raises_rather_than_defaulting(tmp_path):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    bad = dict(ALPHA, update_window_end="08:00:00")  # ends before it starts
    _write_config(config_dir, bad)

    store = ChannelConfigStore(config_dir)
    with pytest.raises(ValueError):
        store.list_configured_channels()


def test_sync_to_db_upserts_channel_and_config(tmp_path):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, ALPHA)

    db_path = tmp_path / "test.db"
    run_migrations(db_path)

    store = ChannelConfigStore(config_dir)
    assert store.sync_to_db(db_path) == 1

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT roster, channel_owner_id FROM channel_config WHERE channel_id = ?",
        ("chn-alpha",),
    ).fetchone()
    conn.close()

    assert json.loads(row["roster"]) == ["priya", "james", "wei"]
    assert row["channel_owner_id"] == "priya"


def _synced_store(tmp_path, data=ALPHA):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, data)
    db_path = tmp_path / "test.db"
    run_migrations(db_path)
    store = ChannelConfigStore(config_dir)
    store.sync_to_db(db_path)
    return store, config_dir, db_path


def test_resync_keeps_a_live_owner_edit(tmp_path):
    """Regression (2026-09-23): run_daily.py re-syncs YAML on every run,
    which used to silently revert a channel owner's live roster and
    exceptions edits -- e.g. putting someone on leave, then seeing them
    reported as a non-responder again the next morning."""
    store, _, db_path = _synced_store(tmp_path)
    store.update_channel_config(
        "chn-alpha",
        roster=["priya", "james", "wei", "carol"],
        exceptions=[{"member_id": "wei", "reason": "leave"}],
        updated_by="priya",
        db_path=db_path,
    )

    store.sync_to_db(db_path)

    effective = store.get_effective_config("chn-alpha", db_path=db_path)
    assert effective.roster == ["priya", "james", "wei", "carol"]
    assert [e.member_id for e in effective.exceptions] == ["wei"]
    assert effective.version == 2


def test_resync_still_applies_yaml_only_fields(tmp_path):
    store, config_dir, db_path = _synced_store(tmp_path)
    store.update_channel_config("chn-alpha", roster=["priya", "carol"], updated_by="priya", db_path=db_path)
    _write_config(config_dir, dict(ALPHA, nudge_enabled=True, daily_digest_time="12:00:00"))

    store.sync_to_db(db_path)

    effective = store.get_effective_config("chn-alpha", db_path=db_path)
    assert effective.nudge_enabled is True
    assert effective.daily_digest_time.isoformat() == "12:00:00"
    assert effective.roster == ["priya", "carol"]


def test_reset_owner_fields_restores_yaml_and_is_audited(tmp_path):
    store, _, db_path = _synced_store(tmp_path)
    store.update_channel_config("chn-alpha", roster=["priya", "carol"], updated_by="priya", db_path=db_path)

    store.sync_to_db(db_path, reset_owner_fields=True)

    effective = store.get_effective_config("chn-alpha", db_path=db_path)
    assert effective.roster == ["priya", "james", "wei"]
    assert effective.version == 3
    conn = get_connection(db_path)
    actions = [r["action"] for r in conn.execute(
        "SELECT action FROM audit WHERE entity_id = ? ORDER BY id", ("chn-alpha",)
    )]
    conn.close()
    assert actions == ["channel_config.updated", "channel_config.reset_from_yaml"]


# --- the weekly roll-up must fire after the day's work is done (2026-09-24) ------------

def _load(tmp_path, data):
    config_dir = tmp_path / "channels"
    config_dir.mkdir()
    _write_config(config_dir, data)
    return ChannelConfigStore(config_dir)


def test_weekly_time_before_the_update_window_closes_is_rejected(tmp_path):
    """The real misconfiguration found live: p1-agent-test's window closed
    at 17:30 but its weekly roll-up fired at 16:00, so the week's last day
    was summarised while people could still post."""
    bad = dict(ALPHA, update_window_end="17:30:00", daily_digest_time="17:30:00", weekly_digest_time="16:00:00")
    with pytest.raises(Exception, match="weekly_digest_time"):
        _load(tmp_path, bad).list_configured_channels()


def test_weekly_time_equal_to_the_window_end_is_rejected(tmp_path):
    bad = dict(ALPHA, update_window_end="11:00:00", daily_digest_time="11:00:00", weekly_digest_time="11:00:00")
    with pytest.raises(Exception, match="weekly_digest_time"):
        _load(tmp_path, bad).list_configured_channels()


def test_weekly_time_before_the_daily_digest_is_rejected_even_after_the_window(tmp_path):
    bad = dict(ALPHA, update_window_end="11:00:00", daily_digest_time="12:00:00", weekly_digest_time="11:30:00")
    with pytest.raises(Exception, match="daily_digest_time"):
        _load(tmp_path, bad).list_configured_channels()


def test_weekly_time_after_both_the_window_and_the_daily_digest_is_accepted(tmp_path):
    good = dict(ALPHA, update_window_end="17:30:00", daily_digest_time="17:30:00", weekly_digest_time="17:45:00")
    assert _load(tmp_path, good).get_channel_config("chn-alpha").weekly_digest_time.strftime("%H:%M") == "17:45"
