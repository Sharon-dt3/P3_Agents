import sqlite3

from p1.storage.db import run_migrations


def test_run_migrations_creates_expected_tables(tmp_path):
    db_path = tmp_path / "test.db"

    run_migrations(db_path)

    conn = sqlite3.connect(db_path)
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")
    }
    conn.close()

    expected = {
        "channels", "channel_config", "members", "messages", "messages_fts",
        "classifications", "participation", "digests", "proposals",
        "write_log", "audit", "sync_state", "schema_migrations",
    }
    assert expected.issubset(tables)


def test_run_migrations_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"

    first_run = run_migrations(db_path)
    second_run = run_migrations(db_path)

    assert first_run == ["0001_initial.sql", "0002_sync_state.sql", "0003_channel_config_non_working_dates.sql"]
    assert second_run == []
