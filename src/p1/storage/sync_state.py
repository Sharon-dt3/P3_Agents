"""
Sync state store (CHN-05): persists each channel's delta token between
ingestion runs, so an incremental sync can resume where the last one
left off.
"""

from __future__ import annotations

from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class SyncStateStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = db_path

    def get_delta_token(self, channel_id: str) -> str | None:
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT delta_token FROM sync_state WHERE channel_id = ?", (channel_id,)
            ).fetchone()
        finally:
            conn.close()
        return row["delta_token"] if row else None

    def save_delta_token(self, channel_id: str, delta_token: str) -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO sync_state (channel_id, delta_token, last_synced_at)
                VALUES (:channel_id, :delta_token, datetime('now'))
                ON CONFLICT(channel_id) DO UPDATE SET
                    delta_token = excluded.delta_token,
                    last_synced_at = excluded.last_synced_at
                """,
                {"channel_id": channel_id, "delta_token": delta_token},
            )
            conn.commit()
        finally:
            conn.close()

    def clear_delta_token(self, channel_id: str) -> None:
        """Used on DeltaTokenExpiredError -- forces the next sync to start
        from scratch (delta_token=None)."""
        conn = get_connection(self._db_path)
        try:
            conn.execute("DELETE FROM sync_state WHERE channel_id = ?", (channel_id,))
            conn.commit()
        finally:
            conn.close()
