-- 0001_initial.sql
-- Core schema for P1 Teams Channel Intelligence (SPN-04).

CREATE TABLE IF NOT EXISTS channels (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    allowlisted     INTEGER NOT NULL DEFAULT 0,   -- CHN-04 scope gate
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS channel_config (
    channel_id                  TEXT PRIMARY KEY REFERENCES channels(id),
    roster                      TEXT NOT NULL,     -- JSON list of member IDs (CHN-02)
    update_window_start         TEXT NOT NULL,
    update_window_end           TEXT NOT NULL,
    timezone                    TEXT NOT NULL,
    working_days                TEXT NOT NULL,      -- JSON list, e.g. ["Mon", ..., "Fri"]
    length_floor                INTEGER NOT NULL DEFAULT 10,
    count_thread_replies        INTEGER NOT NULL DEFAULT 1,
    ignore_bots                 INTEGER NOT NULL DEFAULT 1,
    daily_digest_time           TEXT NOT NULL,
    weekly_digest_day           TEXT NOT NULL,
    weekly_digest_time          TEXT NOT NULL,
    nudge_enabled                INTEGER NOT NULL DEFAULT 0,     -- off by default (R2)
    nudge_cap_per_day           INTEGER NOT NULL DEFAULT 1,
    escalation_threshold_days   INTEGER NOT NULL DEFAULT 3,
    channel_owner_id            TEXT NOT NULL,
    exceptions                  TEXT NOT NULL DEFAULT '[]',      -- JSON: leave list (R2)
    version                     INTEGER NOT NULL DEFAULT 1,
    updated_at                  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS members (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    email           TEXT,
    tenant_status   TEXT NOT NULL DEFAULT 'active'   -- active | left
);

CREATE TABLE IF NOT EXISTS messages (
    id                  TEXT PRIMARY KEY,             -- stable Graph message ID
    channel_id          TEXT NOT NULL REFERENCES channels(id),
    author_id           TEXT REFERENCES members(id),
    thread_root_id      TEXT,                          -- NULL if this IS the root
    posted_at           TEXT NOT NULL,                 -- original time, never overwritten on edit
    edited_at           TEXT,
    deleted_at          TEXT,
    is_deleted          INTEGER NOT NULL DEFAULT 0,
    is_bot              INTEGER NOT NULL DEFAULT 0,
    is_system           INTEGER NOT NULL DEFAULT 0,
    body_raw            TEXT,
    body_normalized     TEXT,
    permalink           TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_posted ON messages(channel_id, posted_at);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    body_normalized,
    content='messages',
    content_rowid='rowid'
);

CREATE TABLE IF NOT EXISTS classifications (
    message_id      TEXT PRIMARY KEY REFERENCES messages(id),
    label           TEXT NOT NULL,     -- update | question | blocker | decision | chatter | noise
    confidence      REAL,
    method          TEXT NOT NULL,     -- rule | model
    rule_name       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS participation (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id            TEXT NOT NULL REFERENCES channels(id),
    member_id             TEXT NOT NULL REFERENCES members(id),
    date                  TEXT NOT NULL,
    state                 TEXT NOT NULL,     -- no_message | posted_no_update | excluded
    evidence_message_ids  TEXT NOT NULL DEFAULT '[]',
    created_at            TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(channel_id, member_id, date)
);

CREATE TABLE IF NOT EXISTS digests (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id        TEXT NOT NULL REFERENCES channels(id),
    date              TEXT NOT NULL,
    type              TEXT NOT NULL,     -- daily | weekly
    content           TEXT NOT NULL,
    published_at      TEXT,
    idempotency_key   TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS proposals (
    id                     TEXT PRIMARY KEY,
    type                   TEXT NOT NULL,     -- publish | nudge | escalation | ...
    status                 TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected | applied
    payload                TEXT NOT NULL,
    original_model_output  TEXT,
    source_refs            TEXT NOT NULL DEFAULT '[]',
    approver_id            TEXT,
    created_at             TEXT NOT NULL DEFAULT (datetime('now')),
    decided_at             TEXT,
    idempotency_key        TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS write_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id   TEXT REFERENCES proposals(id),
    action_type   TEXT NOT NULL,      -- post_channel_message | post_direct_message
    target        TEXT NOT NULL,
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL,      -- sent | suppressed | failed
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    details       TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
