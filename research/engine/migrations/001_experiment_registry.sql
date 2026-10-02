CREATE TABLE IF NOT EXISTS experiment_registry (
    experiment_id TEXT PRIMARY KEY,
    trial_id TEXT NOT NULL,
    strategy_family_id TEXT NOT NULL,
    dataset_path TEXT NOT NULL,
    dataset_identity TEXT NOT NULL,
    dataset_sha256 TEXT NOT NULL,
    code_sha256 TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    started_at_ns INTEGER NOT NULL,
    finished_at_ns INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status = 'completed'),
    result_artifact_id TEXT NOT NULL,
    canonical_summary_json TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS experiment_registry_trial_identity_idx
ON experiment_registry (trial_id, dataset_identity, code_sha256, config_sha256);
