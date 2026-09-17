"""
Participation store: the write path for CHN-10's non-responder ledger
into the participation table (SPN-04). One row per (channel_id,
member_id, date) -- upserted, so recomputing a day's ledger (e.g. after
a late-arriving message is ingested and reclassified) replaces its row
rather than duplicating it, exactly like MessageStore's and
ClassificationStore's own upsert-on-reprocess behaviour.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from p1.storage.db import DEFAULT_DB_PATH, get_connection


class ParticipationStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        self._db_path = db_path

    def record(self, records: Iterable) -> None:
        records = list(records)
        if not records:
            return
        conn = get_connection(self._db_path)
        try:
            for record in records:
                conn.execute(
                    """
                    INSERT INTO participation
                        (channel_id, member_id, date, state, evidence_message_ids)
                    VALUES (:channel_id, :member_id, :date, :state, :evidence_message_ids)
                    ON CONFLICT(channel_id, member_id, date) DO UPDATE SET
                        state = excluded.state,
                        evidence_message_ids = excluded.evidence_message_ids
                    """,
                    {
                        "channel_id": record.channel_id,
                        "member_id": record.member_id,
                        "date": record.date,
                        "state": record.state,
                        "evidence_message_ids": json.dumps(list(record.evidence_message_ids)),
                    },
                )
            conn.commit()
        finally:
            conn.close()
