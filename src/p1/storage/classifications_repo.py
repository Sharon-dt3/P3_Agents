"""
Classification store: the one write path into the classifications table
(CHN-09), used for both rule-settled and model-settled messages. This is
the unification detection/rules.py (CHN-08) deliberately deferred --
that module is pure and DB-free by design, and this is the repo the
CHN-09 pipeline calls once a message's fate (rule or model) is known.

record() is an upsert keyed on message_id, so re-running classification
for a message (e.g. after a prompt version bump) replaces its row rather
than erroring or duplicating -- consistent with MessageStore's own
upsert-on-reprocess behaviour.
"""

from __future__ import annotations

from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class ClassificationStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = db_path

    def record(
        self,
        *,
        message_id: str,
        label: str,
        method: str,
        confidence: float | None = None,
        rule_name: str | None = None,
    ) -> None:
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO classifications (message_id, label, confidence, method, rule_name)
                VALUES (:message_id, :label, :confidence, :method, :rule_name)
                ON CONFLICT(message_id) DO UPDATE SET
                    label = excluded.label,
                    confidence = excluded.confidence,
                    method = excluded.method,
                    rule_name = excluded.rule_name,
                    created_at = datetime('now')
                """,
                {
                    "message_id": message_id,
                    "label": label,
                    "confidence": confidence,
                    "method": method,
                    "rule_name": rule_name,
                },
            )
            conn.commit()
        finally:
            conn.close()

    def model_verdicts(self) -> dict[str, tuple[str, float | None, str]]:
        """message_id -> (label, confidence, classified_at) for every row a
        MODEL settled (method='model'). classified_at is when the row was
        last written -- record() refreshes it on every re-record -- so a
        caller can tell "the model has already judged this exact text"
        from "this message was edited after the model saw it". A model
        verdict of 'noise' is never stored, so it is never in this map."""
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(
                "SELECT message_id, label, confidence, created_at FROM classifications WHERE method = 'model'"
            ).fetchall()
        finally:
            conn.close()
        return {r["message_id"]: (r["label"], r["confidence"], r["created_at"]) for r in rows}
