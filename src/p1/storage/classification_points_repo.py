"""
Classification points store (CHN-09 extension, 2026-10-01): the write
path into classification_points (migration 0007) -- the per-point
breakdown of a message that genuinely contains more than one distinct
thing. Purely additive alongside ClassificationStore/classifications:
nothing here is read by rules.py, the participation ledger, or any
existing golden-case eval -- only digest rendering (gather_daily_facts /
weekly_facts.py) ever reads this table, to route a message's individual
points to their own correct section instead of its single dominant
label deciding the whole message's section.

replace_for_message() -- not an append -- so re-classifying a message
(a prompt-version bump, an edited message re-judged) replaces its prior
point breakdown rather than accumulating stale rows alongside fresh
ones, the same re-run safety ClassificationStore.record()'s own upsert
already gives the single-label path.
"""

from __future__ import annotations

from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class ClassificationPointsStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = db_path

    def replace_for_message(
        self, *, message_id: str, points: list[tuple[str, str, float | None]],
    ) -> None:
        """points is [(label, point_text, confidence), ...]. An empty list
        is a real, meaningful answer (this message was judged NOT to be
        multi-point) and still clears any stale prior breakdown -- never
        skipped as a no-op."""
        conn = get_connection(self._db_path)
        try:
            conn.execute("DELETE FROM classification_points WHERE message_id = ?", (message_id,))
            conn.executemany(
                """
                INSERT INTO classification_points (message_id, label, point_text, confidence)
                VALUES (?, ?, ?, ?)
                """,
                [(message_id, label, point_text, confidence) for label, point_text, confidence in points],
            )
            conn.commit()
        finally:
            conn.close()

    def for_messages(self, message_ids: list[str]) -> dict[str, list[dict]]:
        """message_id -> [{"label":..., "point_text":..., "confidence":...}, ...],
        for every message_id in the given list that has at least one
        stored point. A message_id with no rows here simply never
        appears as a key -- the caller's own fallback-to-single-label
        behaviour is unconditional on that absence, not on an explicit
        empty-list marker, so a never-re-examined message (most of them)
        and a genuinely single-point message behave identically to a
        caller: neither has an entry."""
        if not message_ids:
            return {}
        conn = get_connection(self._db_path)
        try:
            placeholders = ", ".join("?" for _ in message_ids)
            rows = conn.execute(
                f"SELECT message_id, label, point_text, confidence FROM classification_points "
                f"WHERE message_id IN ({placeholders}) ORDER BY id",
                message_ids,
            ).fetchall()
        finally:
            conn.close()
        out: dict[str, list[dict]] = {}
        for row in rows:
            out.setdefault(row["message_id"], []).append(
                {"label": row["label"], "point_text": row["point_text"], "confidence": row["confidence"]}
            )
        return out
