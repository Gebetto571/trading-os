CREATE TABLE IF NOT EXISTS artifacts (
    artifact_id TEXT PRIMARY KEY CHECK (
        length(artifact_id) = 64 AND artifact_id NOT GLOB '*[^0-9a-f]*'
    ),
    artifact_type TEXT NOT NULL CHECK (artifact_type IN (
        'DataSnapshot', 'ExperimentRun', 'StrategyCandidate', 'StrategyPackage',
        'Replay', 'Paper', 'Decision'
    )),
    identity_sha256 TEXT NOT NULL CHECK (
        length(identity_sha256) = 64 AND identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    content_sha256 TEXT NOT NULL CHECK (
        length(content_sha256) = 64 AND content_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    canonical_payload_json TEXT NOT NULL,
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
    UNIQUE (artifact_type, identity_sha256)
);

CREATE TABLE IF NOT EXISTS relations (
    parent_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    child_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    relation_type TEXT NOT NULL CHECK (relation_type = 'derives_from'),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
    PRIMARY KEY (parent_artifact_id, child_artifact_id, relation_type),
    CHECK (parent_artifact_id <> child_artifact_id)
);

CREATE TABLE IF NOT EXISTS trials (
    trial_id TEXT PRIMARY KEY CHECK (length(trial_id) > 0),
    strategy_family_id TEXT NOT NULL CHECK (length(strategy_family_id) > 0),
    identity_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(identity_sha256) = 64 AND identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0)
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY REFERENCES experiment_registry(experiment_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    trial_id TEXT NOT NULL REFERENCES trials(trial_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    data_snapshot_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    experiment_run_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    code_sha256 TEXT NOT NULL CHECK (
        length(code_sha256) = 64 AND code_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    config_sha256 TEXT NOT NULL CHECK (
        length(config_sha256) = 64 AND config_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    result_artifact_id TEXT NOT NULL CHECK (
        length(result_artifact_id) = 64 AND result_artifact_id NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
    UNIQUE (trial_id, data_snapshot_artifact_id, code_sha256, config_sha256)
);

CREATE TABLE IF NOT EXISTS promotions (
    promotion_id TEXT PRIMARY KEY CHECK (
        length(promotion_id) = 64 AND promotion_id NOT GLOB '*[^0-9a-f]*'
    ),
    source_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    target_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    decision_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    promotion_sha256 TEXT NOT NULL CHECK (
        length(promotion_sha256) = 64 AND promotion_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
    UNIQUE (source_artifact_id, target_artifact_id, decision_artifact_id)
);

CREATE TRIGGER IF NOT EXISTS relations_require_adjacent_chain
BEFORE INSERT ON relations
FOR EACH ROW
WHEN (
    NOT EXISTS (SELECT 1 FROM artifacts WHERE artifact_id = NEW.parent_artifact_id)
    OR NOT EXISTS (SELECT 1 FROM artifacts WHERE artifact_id = NEW.child_artifact_id)
    OR NOT (
    (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.parent_artifact_id) = 'DataSnapshot'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.child_artifact_id) = 'ExperimentRun'
    OR (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.parent_artifact_id) = 'ExperimentRun'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.child_artifact_id) = 'StrategyCandidate'
    OR (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.parent_artifact_id) = 'StrategyCandidate'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.child_artifact_id) = 'StrategyPackage'
    OR (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.parent_artifact_id) = 'StrategyPackage'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.child_artifact_id) = 'Replay'
    OR (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.parent_artifact_id) = 'Replay'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.child_artifact_id) = 'Paper'
    OR (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.parent_artifact_id) = 'Paper'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.child_artifact_id) = 'Decision'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'lineage relation requires existing adjacent artifacts');
END;

CREATE TRIGGER IF NOT EXISTS experiments_require_existing_contract
BEFORE INSERT ON experiments
FOR EACH ROW
WHEN (
    NOT EXISTS (SELECT 1 FROM experiment_registry WHERE experiment_id = NEW.experiment_id)
    OR NOT EXISTS (SELECT 1 FROM trials WHERE trial_id = NEW.trial_id)
    OR NOT EXISTS (
        SELECT 1 FROM artifacts
        WHERE artifact_id = NEW.data_snapshot_artifact_id AND artifact_type = 'DataSnapshot'
    )
    OR NOT EXISTS (
        SELECT 1 FROM artifacts
        WHERE artifact_id = NEW.experiment_run_artifact_id AND artifact_type = 'ExperimentRun'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'experiment requires existing immutable lineage');
END;

CREATE TRIGGER IF NOT EXISTS promotions_require_existing_artifacts
BEFORE INSERT ON promotions
FOR EACH ROW
WHEN (
    NOT EXISTS (SELECT 1 FROM artifacts WHERE artifact_id = NEW.source_artifact_id)
    OR NOT EXISTS (SELECT 1 FROM artifacts WHERE artifact_id = NEW.target_artifact_id)
    OR NOT EXISTS (SELECT 1 FROM artifacts WHERE artifact_id = NEW.decision_artifact_id)
)
BEGIN
    SELECT RAISE(ABORT, 'promotion requires existing immutable artifacts');
END;

CREATE TRIGGER IF NOT EXISTS artifacts_no_replace
BEFORE INSERT ON artifacts
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM artifacts
    WHERE artifact_id = NEW.artifact_id
       OR (artifact_type = NEW.artifact_type AND identity_sha256 = NEW.identity_sha256)
)
BEGIN
    SELECT RAISE(ABORT, 'artifact replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS relations_no_replace
BEFORE INSERT ON relations
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM relations
    WHERE parent_artifact_id = NEW.parent_artifact_id
      AND child_artifact_id = NEW.child_artifact_id
      AND relation_type = NEW.relation_type
)
BEGIN
    SELECT RAISE(ABORT, 'relation replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trials_no_replace
BEFORE INSERT ON trials
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM trials
    WHERE trial_id = NEW.trial_id OR identity_sha256 = NEW.identity_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'trial replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS experiments_no_replace
BEFORE INSERT ON experiments
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM experiments
    WHERE experiment_id = NEW.experiment_id
       OR (
            trial_id = NEW.trial_id
            AND data_snapshot_artifact_id = NEW.data_snapshot_artifact_id
            AND code_sha256 = NEW.code_sha256
            AND config_sha256 = NEW.config_sha256
       )
)
BEGIN
    SELECT RAISE(ABORT, 'experiment replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS promotions_no_replace
BEFORE INSERT ON promotions
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM promotions
    WHERE promotion_id = NEW.promotion_id
       OR (
            source_artifact_id = NEW.source_artifact_id
            AND target_artifact_id = NEW.target_artifact_id
            AND decision_artifact_id = NEW.decision_artifact_id
       )
)
BEGIN
    SELECT RAISE(ABORT, 'promotion replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS experiment_registry_no_replace
BEFORE INSERT ON experiment_registry
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM experiment_registry
    WHERE experiment_id = NEW.experiment_id
       OR (
            trial_id = NEW.trial_id
            AND dataset_identity = NEW.dataset_identity
            AND code_sha256 = NEW.code_sha256
            AND config_sha256 = NEW.config_sha256
       )
)
BEGIN
    SELECT RAISE(ABORT, 'experiment registry replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS schema_migrations_no_replace
BEFORE INSERT ON schema_migrations
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM schema_migrations WHERE migration_name = NEW.migration_name
)
BEGIN
    SELECT RAISE(ABORT, 'migration marker replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS schema_migrations_no_update
BEFORE UPDATE ON schema_migrations
BEGIN
    SELECT RAISE(ABORT, 'migration markers are immutable');
END;

CREATE TRIGGER IF NOT EXISTS schema_migrations_no_delete
BEFORE DELETE ON schema_migrations
BEGIN
    SELECT RAISE(ABORT, 'migration marker deletion is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS artifacts_no_update
BEFORE UPDATE ON artifacts
BEGIN
    SELECT RAISE(ABORT, 'artifacts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS artifacts_no_delete
BEFORE DELETE ON artifacts
BEGIN
    SELECT RAISE(ABORT, 'physical artifact purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS experiment_registry_no_update
BEFORE UPDATE ON experiment_registry
BEGIN
    SELECT RAISE(ABORT, 'experiment registry records are immutable');
END;

CREATE TRIGGER IF NOT EXISTS experiment_registry_no_delete
BEFORE DELETE ON experiment_registry
BEGIN
    SELECT RAISE(ABORT, 'physical experiment registry purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS relations_no_update
BEFORE UPDATE ON relations
BEGIN
    SELECT RAISE(ABORT, 'relations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS relations_no_delete
BEFORE DELETE ON relations
BEGIN
    SELECT RAISE(ABORT, 'physical relation purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trials_no_update
BEFORE UPDATE ON trials
BEGIN
    SELECT RAISE(ABORT, 'trials are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trials_no_delete
BEFORE DELETE ON trials
BEGIN
    SELECT RAISE(ABORT, 'physical trial purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS experiments_no_update
BEFORE UPDATE ON experiments
BEGIN
    SELECT RAISE(ABORT, 'experiments are immutable');
END;

CREATE TRIGGER IF NOT EXISTS experiments_no_delete
BEFORE DELETE ON experiments
BEGIN
    SELECT RAISE(ABORT, 'physical experiment purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS promotions_no_update
BEFORE UPDATE ON promotions
BEGIN
    SELECT RAISE(ABORT, 'promotions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS promotions_no_delete
BEFORE DELETE ON promotions
BEGIN
    SELECT RAISE(ABORT, 'physical promotion purge is forbidden');
END;
