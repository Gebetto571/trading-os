DROP TRIGGER IF EXISTS relations_require_adjacent_chain;

CREATE TRIGGER relations_require_adjacent_chain
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
