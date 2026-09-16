-- 0002_sync_state.sql
-- Per-channel delta-sync bookkeeping (CHN-05): where an incremental
-- ingest run left off, so the next run can resume from there.

CREATE TABLE IF NOT EXISTS sync_state (
    channel_id      TEXT PRIMARY KEY REFERENCES channels(id),
    delta_token     TEXT,
    last_synced_at  TEXT
);
