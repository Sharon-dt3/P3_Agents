"""
Member display-name resolution, shared by every surface that names a
specific person for a human reader (CHN-14's participation rendering,
CHN-23's escalation messages).

resolve_display_name() moved here from p1.escalations.escalation_job's
own private _resolve_display_name (2026-09-23) so a second caller
(participation_rendering.py) can reuse it instead of re-implementing
the same lookup-with-fallback a second time -- exactly the kind of
drift escalation_job.py's own docstring already warned against for
wording, now true of this lookup too.

KNOWN_NAMES_PATH backstops resolve_display_name() for the real gap it
cannot itself close: messages_repo.py's _ensure_member_exists registers
a never-before-seen author_id with itself as a placeholder
display_name, because Graph's delta payload never carries a real name
and ChannelMember.Read.All (the permission that would let this system
resolve one itself) is not yet granted. config/known_member_names.yaml
is the versioned-config answer to that gap: a human-confirmed mapping,
checked into git, applied by apply_known_names() to any member row
still sitting on its own placeholder -- never to a row a real Graph
sync has already resolved a richer name into.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import yaml

from p1.storage.db import DEFAULT_DB_PATH, get_connection

KNOWN_NAMES_PATH = Path("config/known_member_names.yaml")


def resolve_display_name(member_id: str, *, db_path: str | Path = DEFAULT_DB_PATH) -> str:
    """This person's current members.display_name -- a real name once
    either a real Graph sync or apply_known_names() has corrected the
    auto-registered placeholder (see messages_repo.py's own
    _ensure_member_exists docstring), still just their AAD id
    otherwise, since that is exactly what auto-registration stores
    until then. Falls back to member_id itself if the member row -- or
    even the members table itself -- is somehow missing entirely (a
    bare, un-migrated db_path a small standalone test hands this
    function directly, never real production data where init_db()
    always runs first): no caller of this function may ever crash over
    a missing name."""
    conn = get_connection(db_path)
    try:
        try:
            row = conn.execute("SELECT display_name FROM members WHERE id = ?", (member_id,)).fetchone()
        except sqlite3.OperationalError:
            return member_id
    finally:
        conn.close()
    return row["display_name"] if row and row["display_name"] else member_id


def load_known_names(path: str | Path = KNOWN_NAMES_PATH) -> dict[str, str]:
    """member_id -> confirmed real display_name, from the committed
    config file. An absent file (e.g. a fresh checkout before anyone
    has confirmed a name) is not an error -- it just means nothing to
    apply yet, same honest-empty-state convention this project uses
    elsewhere rather than treating "nothing recorded" as a failure."""
    file_path = Path(path)
    if not file_path.exists():
        return {}
    data = yaml.safe_load(file_path.read_text()) or {}
    return {str(member_id): str(name) for member_id, name in data.items()}


def apply_known_names(*, db_path: str | Path = DEFAULT_DB_PATH, known_names_path: str | Path = KNOWN_NAMES_PATH) -> int:
    """Applies config/known_member_names.yaml to the members table,
    updating display_name ONLY for a row still sitting on the
    auto-registration placeholder (display_name == id) -- a row a real
    Graph sync has already given a richer name to is never touched,
    same guarantee _ensure_member_exists's own INSERT OR IGNORE already
    makes for row creation. Safe to call any number of times (a no-op
    once every known row is already corrected); returns the number of
    rows actually changed this call."""
    known_names = load_known_names(known_names_path)
    if not known_names:
        return 0

    conn = get_connection(db_path)
    try:
        updated = 0
        for member_id, display_name in known_names.items():
            cursor = conn.execute(
                "UPDATE members SET display_name = ? WHERE id = ? AND display_name = ?",
                (display_name, member_id, member_id),
            )
            updated += cursor.rowcount
        conn.commit()
    finally:
        conn.close()
    return updated
