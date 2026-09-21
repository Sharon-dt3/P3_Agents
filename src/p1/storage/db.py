"""
Thin re-export shim -- CHN-33: get_connection() (the generic connection
helper) now lives in spine.storage.db, moved there verbatim. DO NOT make
this a blanket `from spine.storage.db import *`: run_migrations()'s own
migrations_dir default binds to whichever module defines it, and P1's real
schema lives in src/p1/storage/migrations/ (six real migration files), not
in spine's own (nonexistent) migrations directory. run_migrations() and
init_db() are therefore redefined here as thin wrappers that always pass
P1's own MIGRATIONS_DIR through explicitly, so every existing call site --
most of which call init_db()/run_migrations() with no migrations_dir
argument at all -- keeps applying P1's own committed schema exactly as
before. See DECISION_LOG.md, 2026-09-21 CHN-33 entry.
"""

from __future__ import annotations

import logging
from pathlib import Path

from spine.storage.db import DEFAULT_DB_PATH, get_connection
from spine.storage.db import run_migrations as _spine_run_migrations

logger = logging.getLogger("p1.storage.db")

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

__all__ = ["DEFAULT_DB_PATH", "MIGRATIONS_DIR", "get_connection", "run_migrations", "init_db"]


def run_migrations(
    db_path: str | Path = DEFAULT_DB_PATH,
    migrations_dir: Path = MIGRATIONS_DIR,
) -> list[str]:
    """Apply every migration not yet recorded as applied, in filename order.
    Delegates to spine.storage.db's real engine, always passing P1's own
    migrations_dir through explicitly (see this module's own docstring for
    why that default cannot simply be inherited from spine's function)."""
    return _spine_run_migrations(db_path, migrations_dir)


def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    """Seed-command entry point: build a fresh DB from P1's own migrations
    alone. Unchanged behaviour from before CHN-33."""
    applied = run_migrations(db_path)
    if applied:
        logger.info("Database initialised at %s (%d migration(s) applied)", db_path, len(applied))
    else:
        logger.info("Database at %s already up to date", db_path)
