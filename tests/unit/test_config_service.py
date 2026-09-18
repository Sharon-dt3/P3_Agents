"""
CHN-25: get_effective_config()/update_channel_config(), the live
read/write path a channel owner uses to maintain their own roster,
update window and exceptions list without a deploy.

Every test here seeds a channel the same way production bootstraps one
-- a committed YAML file, loaded and sync_to_db()'d into SQLite -- then
exercises the NEW live path against that same database, never the
files directly, since that live path (not the files) is what this row
adds.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from p1.config.loader import ChannelConfigStore
from p1.config.schema import ExceptionEntry
from p1.storage.db import get_connection, init_db

ALPHA = {
    "channel_id": "chn-alpha", "display_name": "Project Alpha", "allowlisted": True,
    "roster": ["priya", "james", "wei"],
    "update_window_start": "09:00:00", "update_window_end": "11:00:00",
    "timezone": "Asia/Colombo", "working_days": ["Mon", "Tue", "Wed", "Thu", "Fri"],
    "daily_digest_time": "11:30:00", "weekly_digest_day": "Fri", "weekly_digest_time": "16:00:00",
    "channel_owner_id": "priya",
}


def _seed(tmp_path: Path, db_path: Path, data: dict = ALPHA) -> ChannelConfigStore:
    config_dir = tmp_path / "channels"
    config_dir.mkdir(exist_ok=True)
    (config_dir / f"{data['channel_id']}.yaml").write_text(yaml.safe_dump(data))
    init_db(db_path)
    store = ChannelConfigStore(config_dir)
    store.sync_to_db(db_path=db_path)
    return store


def test_get_effective_config_round_trips_the_synced_config(tmp_path):
    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    effective = store.get_effective_config("chn-alpha", db_path=db_path)

    assert effective.roster == ALPHA["roster"]
    assert effective.channel_owner_id == "priya"
    assert effective.version == 1


def test_get_effective_config_raises_for_an_unsynced_channel(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(db_path)
    store = ChannelConfigStore(tmp_path / "channels")

    with pytest.raises(KeyError):
        store.get_effective_config("nope", db_path=db_path)


def test_update_channel_config_changes_only_the_given_fields(tmp_path):
    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    updated = store.update_channel_config(
        "chn-alpha", roster=["priya", "james"], updated_by="priya", db_path=db_path,
    )

    assert updated.roster == ["priya", "james"]
    # everything else, including the window and timezone, is untouched
    assert updated.update_window_start.isoformat() == "09:00:00"
    assert updated.timezone == "Asia/Colombo"
    assert updated.version == 2


def test_update_channel_config_takes_effect_immediately_with_no_deploy(tmp_path):
    """The whole point of this row: a live edit changes what
    get_effective_config() returns on the very next call, with no
    re-sync, no file edit, no deploy."""
    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    store.update_channel_config("chn-alpha", roster=["priya"], updated_by="priya", db_path=db_path)

    assert store.get_effective_config("chn-alpha", db_path=db_path).roster == ["priya"]


def test_update_channel_config_updates_the_window_and_exceptions(tmp_path):
    from datetime import time

    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    updated = store.update_channel_config(
        "chn-alpha",
        update_window_start=time(8, 0),
        update_window_end=time(9, 30),
        exceptions=[{"member_id": "james", "reason": "On leave"}],
        updated_by="priya",
        db_path=db_path,
    )

    assert updated.update_window_start == time(8, 0)
    assert updated.update_window_end == time(9, 30)
    assert updated.exceptions == [ExceptionEntry(member_id="james", reason="On leave")]


def test_update_channel_config_rejects_an_invalid_window_without_writing_anything(tmp_path):
    """Re-validation is of the WHOLE resulting config, not just the
    field that changed -- an update that would make the window backwards
    is refused outright, and nothing is written or audited."""
    from datetime import time

    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    with pytest.raises(ValueError):
        store.update_channel_config(
            "chn-alpha", update_window_start=time(11, 0), update_window_end=time(9, 0),
            updated_by="priya", db_path=db_path,
        )

    unchanged = store.get_effective_config("chn-alpha", db_path=db_path)
    assert unchanged.update_window_start.isoformat() == "09:00:00"
    assert unchanged.version == 1

    conn = get_connection(db_path)
    try:
        audit_count = conn.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
    finally:
        conn.close()
    assert audit_count == 0


def test_update_channel_config_rejects_an_empty_roster(tmp_path):
    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    with pytest.raises(ValueError):
        store.update_channel_config("chn-alpha", roster=[], updated_by="priya", db_path=db_path)


def test_update_channel_config_with_no_fields_given_is_a_no_op(tmp_path):
    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    result = store.update_channel_config("chn-alpha", updated_by="priya", db_path=db_path)

    assert result.version == 1  # unchanged
    conn = get_connection(db_path)
    try:
        audit_count = conn.execute("SELECT COUNT(*) AS n FROM audit").fetchone()["n"]
    finally:
        conn.close()
    assert audit_count == 0


def test_update_channel_config_writes_one_audit_row_with_before_and_after(tmp_path):
    import json

    db_path = tmp_path / "test.db"
    store = _seed(tmp_path, db_path)

    store.update_channel_config("chn-alpha", roster=["priya", "james"], updated_by="priya", db_path=db_path)

    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM audit WHERE entity_type = 'channel_config' AND entity_id = 'chn-alpha'"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["actor"] == "priya"
    assert row["action"] == "channel_config.updated"
    details = json.loads(row["details"])
    assert details["roster"]["old"] == ["priya", "james", "wei"]
    assert details["roster"]["new"] == ["priya", "james"]
