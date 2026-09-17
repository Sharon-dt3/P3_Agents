"""
Digest store (CHN-13): the one write path into the digests table for a
generated summary's rendered content.

record() is an upsert keyed on idempotency_key, so regenerating a day's
digest before it has been published (CHN-17's job, not this one)
replaces its content in place rather than duplicating a row --
consistent with every other store in this codebase (MessageStore,
ClassificationStore, ParticipationStore all upsert-on-reprocess the same
way). published_at is deliberately never touched here: publishing a
digest, and enforcing that a digest is only ever published once, is
CHN-17/CHN-18's concern, not this module's.
"""

from __future__ import annotations

from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class DigestStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = db_path

    def record(
        self,
        *,
        channel_id: str,
        date: str,
        type: str,
        content: str,
        idempotency_key: str,
    ) -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO digests (channel_id, date, type, content, idempotency_key)
                VALUES (:channel_id, :date, :type, :content, :idempotency_key)
                ON CONFLICT(idempotency_key) DO UPDATE SET
                    content = excluded.content
                """,
                {
                    "channel_id": channel_id,
                    "date": date,
                    "type": type,
                    "content": content,
                    "idempotency_key": idempotency_key,
                },
            )
            conn.commit()
        finally:
            conn.close()

    def get_by_idempotency_key(self, idempotency_key: str) -> dict | None:
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT channel_id, date, type, content, published_at, idempotency_key "
                "FROM digests WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        finally:
            conn.close()
        return dict(row) if row is not None else None
