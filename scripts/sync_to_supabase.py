"""
Mirrors data/p1_live.db into a Supabase Postgres project, purely for
live human viewing/sharing -- NOT part of the scored system. SQLite
remains the actual system of record, exactly as the implementation
plan specifies (DB | SQLite + FTS5); nothing here is read back by any
capability, job, or test. This is a one-way, read-only-from-the-app's-
perspective copy so a channel owner or lead can open Supabase's own
Table Editor and see the real data update, without needing to be on
your laptop or in a screen-share.

Every mirrored column is stored as TEXT regardless of its SQLite type.
That is a deliberate simplification: this script exists to make data
human-readable in a browser, not to be queried or computed against, so
there is no reason to fight SQLite's dynamic typing against Postgres's
strict one. FTS5's own internal tables (messages_fts and its shadow
tables) are skipped entirely -- they are SQLite full-text-search
implementation detail, meaningless outside SQLite and not real
project data.

Requires SUPABASE_DB_URL in .env (a full postgres:// connection URI,
password percent-encoded). Safe to run repeatedly -- every table is
created if missing and every row is upserted on its real primary key,
so re-running this after any ingest is exactly how you keep the
mirror current.

Usage:
    uv run python scripts/sync_to_supabase.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv

load_dotenv()

import psycopg2
import psycopg2.extras

SQLITE_PATH = "data/p1_live.db"

# (table_name, primary_key_column) -- every table this repo actually
# uses for real project data. FTS5's own tables are deliberately
# excluded (see module docstring).
MIRROR_TABLES = [
    ("channels", "id"),
    ("channel_config", "channel_id"),
    ("members", "id"),
    ("messages", "id"),
    ("classifications", "message_id"),
    ("participation", "id"),
    ("proposals", "id"),
    ("digests", "id"),
    ("nudges", "id"),
    ("escalations", "id"),
    ("write_log", "id"),
    ("audit", "id"),
    ("sync_state", "channel_id"),
    ("schema_migrations", "filename"),
]


def _sqlite_columns(sconn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in sconn.execute(f"PRAGMA table_info({table})").fetchall()]


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def sync_table(sconn: sqlite3.Connection, pconn, table: str, pk: str) -> int:
    columns = _sqlite_columns(sconn, table)
    if not columns:
        return 0  # table doesn't exist in this sqlite db (e.g. a fresh clone) -- skip, not an error

    col_list = ", ".join(_quote_ident(c) for c in columns)
    create_cols = ", ".join(f"{_quote_ident(c)} TEXT" for c in columns)

    with pconn.cursor() as cur:
        cur.execute(
            f'CREATE TABLE IF NOT EXISTS {_quote_ident(table)} '
            f'({create_cols}, PRIMARY KEY ({_quote_ident(pk)}))'
        )

        rows = sconn.execute(f"SELECT {col_list} FROM {table}").fetchall()
        if not rows:
            pconn.commit()
            return 0

        str_rows = [tuple(None if v is None else str(v) for v in row) for row in rows]

        update_cols = [c for c in columns if c != pk]
        set_clause = ", ".join(f"{_quote_ident(c)} = EXCLUDED.{_quote_ident(c)}" for c in update_cols)
        conflict_clause = (
            f"ON CONFLICT ({_quote_ident(pk)}) DO UPDATE SET {set_clause}"
            if update_cols
            else f"ON CONFLICT ({_quote_ident(pk)}) DO NOTHING"
        )

        placeholders = ", ".join(["%s"] * len(columns))
        psycopg2.extras.execute_batch(
            cur,
            f"INSERT INTO {_quote_ident(table)} ({col_list}) VALUES ({placeholders}) {conflict_clause}",
            str_rows,
        )
        pconn.commit()

    return len(rows)


def run_sync(*, sqlite_path: str = SQLITE_PATH, db_url: str | None = None) -> int:
    db_url = db_url or os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        print("SUPABASE_DB_URL must be set in .env -- copy the Direct connection URI "
              "from Supabase's Project Settings -> Database, with the password "
              "percent-encoded.")
        return 1

    sconn = sqlite3.connect(sqlite_path)
    pconn = psycopg2.connect(db_url)
    try:
        print(f"Syncing {sqlite_path} -> Supabase ...")
        total = 0
        for table, pk in MIRROR_TABLES:
            count = sync_table(sconn, pconn, table, pk)
            print(f"  {table}: {count} row(s) synced")
            total += count
        print(f"Done -- {total} row(s) across {len(MIRROR_TABLES)} table(s). "
              "Open your Supabase project's Table Editor to see them.")
        return 0
    finally:
        sconn.close()
        pconn.close()


def main() -> int:
    return run_sync()


if __name__ == "__main__":
    raise SystemExit(main())
