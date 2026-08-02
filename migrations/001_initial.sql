PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    received_at TEXT,
    sender TEXT NOT NULL,
    recipient TEXT NOT NULL,
    message_type TEXT NOT NULL CHECK (message_type IN ('task', 'response', 'decision', 'status', 'error')),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    correlation_id TEXT,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'received', 'processing', 'completed', 'failed')),
    source_uri TEXT,
    payload_json TEXT NOT NULL,
    error_text TEXT,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_status ON messages(status, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_correlation ON messages(correlation_id);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT,
    name TEXT NOT NULL,
    uri TEXT NOT NULL,
    sha256 TEXT,
    media_type TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'accepted', 'superseded', 'rejected')),
    version INTEGER NOT NULL,
    body TEXT NOT NULL,
    source_message_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (source_message_id) REFERENCES messages(id),
    UNIQUE (id, version)
);

CREATE TABLE IF NOT EXISTS sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    direction TEXT NOT NULL CHECK (direction IN ('pull', 'push')),
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    item_count INTEGER NOT NULL DEFAULT 0,
    detail TEXT
);

