ALTER TABLE messages ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE messages ADD COLUMN updated_by TEXT;
ALTER TABLE messages ADD COLUMN base_commit TEXT;
ALTER TABLE messages ADD COLUMN project_domain TEXT;
ALTER TABLE messages ADD COLUMN cloud_conversation_key TEXT;
ALTER TABLE messages ADD COLUMN local_lane TEXT;
ALTER TABLE messages ADD COLUMN authority TEXT;
ALTER TABLE messages ADD COLUMN approval_state TEXT;
ALTER TABLE messages ADD COLUMN active_writer TEXT;
ALTER TABLE messages ADD COLUMN owned_paths_json TEXT;
ALTER TABLE messages ADD COLUMN verification_verdict TEXT;
ALTER TABLE messages ADD COLUMN result_message_id TEXT;

CREATE INDEX idx_messages_chief_engineer_claimable
ON messages(direction, status, authority, approval_state, local_lane, created_at);

CREATE INDEX idx_messages_active_writer
ON messages(status, active_writer);
