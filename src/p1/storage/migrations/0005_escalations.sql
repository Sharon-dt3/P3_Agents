CREATE TABLE IF NOT EXISTS escalations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id          TEXT NOT NULL REFERENCES channels(id),
    member_id           TEXT NOT NULL REFERENCES members(id),
    streak_start_date   TEXT NOT NULL,
    date                TEXT NOT NULL,
    proposal_id         TEXT,
    sent_at             TEXT,
    idempotency_key     TEXT NOT NULL UNIQUE,
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_escalations_channel_member ON escalations(channel_id, member_id);
