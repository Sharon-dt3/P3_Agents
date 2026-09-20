-- 0006_messages_fts_sync.sql
-- Wires up messages_fts (declared in 0001_initial.sql on day one, never
-- actually populated -- see DECISION_LOG.md's 2026-09-20 entry). It is
-- an external-content FTS5 table (content='messages',
-- content_rowid='rowid'): SQLite does not sync it automatically, and
-- with no triggers and nothing else ever calling INSERT/rebuild on it,
-- it has stayed permanently empty regardless of how many rows
-- `messages` has gained.

CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, body_normalized) VALUES (new.rowid, new.body_normalized);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body_normalized) VALUES ('delete', old.rowid, old.body_normalized);
END;

CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
    INSERT INTO messages_fts(messages_fts, rowid, body_normalized) VALUES ('delete', old.rowid, old.body_normalized);
    INSERT INTO messages_fts(rowid, body_normalized) VALUES (new.rowid, new.body_normalized);
END;

-- One-time backfill: every message ingested before this migration ran
-- (real ones included -- p1-agent-test already has several) exists in
-- `messages` but was never indexed. 'rebuild' recomputes the entire FTS
-- index from messages' current contents in a single pass.
INSERT INTO messages_fts(messages_fts) VALUES ('rebuild');
