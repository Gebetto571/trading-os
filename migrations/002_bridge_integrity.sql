ALTER TABLE messages ADD COLUMN payload_sha256 TEXT;
ALTER TABLE messages ADD COLUMN raw_sha256 TEXT;
ALTER TABLE messages ADD COLUMN claimed_by TEXT;
ALTER TABLE messages ADD COLUMN claimed_at TEXT;
ALTER TABLE messages ADD COLUMN lease_until TEXT;
ALTER TABLE messages ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE messages ADD COLUMN last_error TEXT;
ALTER TABLE messages ADD COLUMN quarantined_at TEXT;
ALTER TABLE messages ADD COLUMN quarantine_uri TEXT;

CREATE INDEX IF NOT EXISTS idx_messages_claimable
ON messages(direction, status, lease_until, created_at);

ALTER TABLE decisions RENAME TO decisions_v1;

CREATE TABLE decisions (
    id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed', 'accepted', 'superseded', 'rejected')),
    body TEXT NOT NULL,
    source_message_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (id, version),
    FOREIGN KEY (source_message_id) REFERENCES messages(id)
);

INSERT INTO decisions(id, version, title, status, body, source_message_id, created_at, updated_at)
SELECT id, version, title, status, body, source_message_id, created_at, updated_at
FROM decisions_v1;

DROP TABLE decisions_v1;
CREATE INDEX idx_decisions_latest ON decisions(id, version DESC);
