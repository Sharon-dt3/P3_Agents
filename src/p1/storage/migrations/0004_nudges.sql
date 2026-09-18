CREATE TABLE IF NOT EXISTS nudges (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id        TEXT NOT NULL REFERENCES channels(id),
    member_id         TEXT NOT NULL REFERENCES members(id),
    date              TEXT NOT NULL,
    proposal_id       TEXT,
    sent_at           TEXT,
    idempotency_key   TEXT NOT NULL UNIQUE,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nudges_channel_member_date ON nudges(channel_id, member_id, date);
