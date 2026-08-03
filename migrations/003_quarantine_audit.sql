ALTER TABLE messages ADD COLUMN terminal_by TEXT;
ALTER TABLE messages ADD COLUMN terminal_at TEXT;

CREATE TABLE quarantine_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('invalid', 'integrity_conflict')),
    source_uri TEXT NOT NULL,
    quarantine_uri TEXT,
    message_id TEXT,
    raw_sha256 TEXT,
    error_text TEXT NOT NULL
);

CREATE INDEX idx_quarantine_events_time ON quarantine_events(occurred_at, id);
