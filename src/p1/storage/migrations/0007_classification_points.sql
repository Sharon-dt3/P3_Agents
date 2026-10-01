-- 0007_classification_points.sql
--
-- A real Teams message is often several distinct things at once -- a
-- bulky update can bundle three pieces of progress, a real blocker and
-- a real question into one message, but `classifications` (0001) can
-- only ever hold ONE label per message, by design (message_id is its
-- PRIMARY KEY) -- rules.py, the participation ledger, and the existing
-- golden-case evals all depend on that single-verdict shape, so it is
-- never touched by this migration.
--
-- This table is purely additive: it holds the finer-grained, per-point
-- breakdown of a message's content (one row per distinct point, each
-- with its own label) used ONLY by digest rendering (gather_daily_facts
-- / weekly_facts.py) to route each point to the right section --
-- "what moved" / blockers / decisions / questions -- instead of the
-- whole message landing in a single section under its one dominant
-- label. A message with only one real point simply gets one row here,
-- or none at all if it was never re-examined -- callers fall back to
-- the existing single-label behaviour (classifications.label) for any
-- message with no rows here, so this is additive, not a replacement.
CREATE TABLE IF NOT EXISTS classification_points (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id      TEXT NOT NULL REFERENCES messages(id),
    label           TEXT NOT NULL,     -- update | question | blocker | decision (never chatter/noise -- see classifier.py)
    point_text      TEXT NOT NULL,     -- the exact, verbatim substring of the message's own body this point is grounded in
    confidence      REAL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_classification_points_message ON classification_points(message_id);
