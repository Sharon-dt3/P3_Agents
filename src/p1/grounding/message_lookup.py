"""
P1-specific adapter: builds a grounding-kernel MessageLookup backed by
this system's own messages table. Kept separate from grounding/kernel.py
deliberately -- the kernel itself must stay domain-agnostic (SPN-06's
WBS: "same module later enforces citation resolution for P2 and P3"),
so anything that knows about SQLite or this system's schema lives here
instead, never inside the kernel.

Verbatim quote-checking is done against body_raw, never
body_normalized: normalization only strips surrounding whitespace for
FTS search (see storage/messages_repo.py's _normalize), and a quote is
either a literal substring of what the person actually wrote or it
isn't -- there is no version of "verbatim" that should tolerate a
transform the person's own message never had applied to it.
"""

from __future__ import annotations

from pathlib import Path

from p1.grounding.kernel import MessageLookup
from p1.storage.db import DEFAULT_DB_PATH, get_connection


def sqlite_message_lookup(db_path: str | Path = DEFAULT_DB_PATH) -> MessageLookup:
    """One connection per lookup call -- the simplest correct answer at
    this system's volumes, consistent with every other store in this
    codebase (MessageStore, ClassificationStore, ParticipationStore all
    do the same); not an oversight to optimise later without a reason
    to."""

    def lookup(message_id: str) -> str | None:
        conn = get_connection(db_path)
        try:
            row = conn.execute("SELECT body_raw FROM messages WHERE id = ?", (message_id,)).fetchone()
        finally:
            conn.close()
        return row["body_raw"] if row is not None else None

    return lookup
