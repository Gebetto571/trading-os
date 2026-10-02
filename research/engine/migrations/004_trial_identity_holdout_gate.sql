CREATE TABLE IF NOT EXISTS trial_identities (
    trial_id TEXT PRIMARY KEY CHECK (
        length(trial_id) = 64 AND trial_id NOT GLOB '*[^0-9a-f]*'
    ) REFERENCES trials(trial_id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    strategy_family_id TEXT NOT NULL CHECK (length(strategy_family_id) > 0),
    data_snapshot_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    dataset_sha256 TEXT NOT NULL CHECK (
        length(dataset_sha256) = 64 AND dataset_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    code_sha256 TEXT NOT NULL CHECK (
        length(code_sha256) = 64 AND code_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    config_sha256 TEXT NOT NULL CHECK (
        length(config_sha256) = 64 AND config_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    identity_sha256 TEXT NOT NULL UNIQUE CHECK (
        length(identity_sha256) = 64 AND identity_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0),
    CHECK (trial_id = identity_sha256),
    UNIQUE (
        strategy_family_id, data_snapshot_artifact_id, dataset_sha256,
        code_sha256, config_sha256
    )
);

CREATE TABLE IF NOT EXISTS holdout_accesses (
    holdout_access_id TEXT PRIMARY KEY CHECK (
        length(holdout_access_id) = 64 AND holdout_access_id NOT GLOB '*[^0-9a-f]*'
    ),
    trial_id TEXT NOT NULL REFERENCES trial_identities(trial_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    evidence_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    accessed_at_ns INTEGER NOT NULL CHECK (accessed_at_ns >= 0),
    UNIQUE (trial_id, evidence_artifact_id, accessed_at_ns)
);

CREATE TABLE IF NOT EXISTS trial_stage_transitions (
    stage_transition_id TEXT PRIMARY KEY CHECK (
        length(stage_transition_id) = 64 AND stage_transition_id NOT GLOB '*[^0-9a-f]*'
    ),
    trial_id TEXT NOT NULL REFERENCES trial_identities(trial_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    from_stage TEXT,
    to_stage TEXT NOT NULL CHECK (to_stage IN (
        'EXPLORATORY', 'CANDIDATE', 'PROMOTABLE', 'LIVE_CANDIDATE'
    )),
    evidence_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    recorded_at_ns INTEGER NOT NULL CHECK (recorded_at_ns >= 0),
    CHECK (
        (from_stage IS NULL AND to_stage = 'EXPLORATORY')
        OR (from_stage = 'EXPLORATORY' AND to_stage = 'CANDIDATE')
        OR (from_stage = 'CANDIDATE' AND to_stage = 'PROMOTABLE')
        OR (from_stage = 'PROMOTABLE' AND to_stage = 'LIVE_CANDIDATE')
    ),
    UNIQUE (trial_id, to_stage)
);

CREATE TRIGGER IF NOT EXISTS trial_identities_require_matching_snapshot
BEFORE INSERT ON trial_identities
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM trials AS trial
    JOIN artifacts AS snapshot ON snapshot.artifact_id = NEW.data_snapshot_artifact_id
    WHERE trial.trial_id = NEW.trial_id
      AND trial.strategy_family_id = NEW.strategy_family_id
      AND snapshot.artifact_type = 'DataSnapshot'
      AND snapshot.content_sha256 = NEW.dataset_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'trial identity requires a matching immutable data snapshot');
END;

CREATE TRIGGER IF NOT EXISTS trial_identities_no_replace
BEFORE INSERT ON trial_identities
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM trial_identities
    WHERE trial_id = NEW.trial_id
       OR identity_sha256 = NEW.identity_sha256
       OR (
            strategy_family_id = NEW.strategy_family_id
            AND data_snapshot_artifact_id = NEW.data_snapshot_artifact_id
            AND dataset_sha256 = NEW.dataset_sha256
            AND code_sha256 = NEW.code_sha256
            AND config_sha256 = NEW.config_sha256
       )
)
BEGIN
    SELECT RAISE(ABORT, 'trial identity replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trial_identities_no_update
BEFORE UPDATE ON trial_identities
BEGIN
    SELECT RAISE(ABORT, 'trial identities are immutable');
END;

CREATE TRIGGER IF NOT EXISTS trial_identities_no_delete
BEFORE DELETE ON trial_identities
BEGIN
    SELECT RAISE(ABORT, 'physical trial identity purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS holdout_accesses_require_trial_snapshot_evidence
BEFORE INSERT ON holdout_accesses
FOR EACH ROW
WHEN NOT EXISTS (
    SELECT 1
    FROM trial_identities AS identity
    WHERE identity.trial_id = NEW.trial_id
      AND identity.data_snapshot_artifact_id = NEW.evidence_artifact_id
)
BEGIN
    SELECT RAISE(ABORT, 'holdout access requires its immutable trial snapshot evidence');
END;

CREATE TRIGGER IF NOT EXISTS holdout_accesses_reject_candidate_or_higher
BEFORE INSERT ON holdout_accesses
FOR EACH ROW
WHEN EXISTS (
    SELECT 1
    FROM trial_stage_transitions
    WHERE trial_id = NEW.trial_id
      AND to_stage IN ('CANDIDATE', 'PROMOTABLE', 'LIVE_CANDIDATE')
)
BEGIN
    SELECT RAISE(ABORT, 'holdout access is forbidden after candidate-or-higher promotion');
END;

CREATE TRIGGER IF NOT EXISTS holdout_accesses_no_replace
BEFORE INSERT ON holdout_accesses
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM holdout_accesses
    WHERE holdout_access_id = NEW.holdout_access_id
       OR (
            trial_id = NEW.trial_id
            AND evidence_artifact_id = NEW.evidence_artifact_id
            AND accessed_at_ns = NEW.accessed_at_ns
       )
)
BEGIN
    SELECT RAISE(ABORT, 'holdout access replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS holdout_accesses_no_update
BEFORE UPDATE ON holdout_accesses
BEGIN
    SELECT RAISE(ABORT, 'holdout accesses are append-only');
END;

CREATE TRIGGER IF NOT EXISTS holdout_accesses_no_delete
BEFORE DELETE ON holdout_accesses
BEGIN
    SELECT RAISE(ABORT, 'physical holdout access purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trial_stage_transitions_require_trial_bound_evidence
BEFORE INSERT ON trial_stage_transitions
FOR EACH ROW
WHEN NOT (
    (
        NEW.to_stage = 'EXPLORATORY'
        AND EXISTS (
            SELECT 1
            FROM trial_identities AS identity
            WHERE identity.trial_id = NEW.trial_id
              AND identity.data_snapshot_artifact_id = NEW.evidence_artifact_id
        )
    )
    OR (
        NEW.to_stage IN ('CANDIDATE', 'PROMOTABLE', 'LIVE_CANDIDATE')
        AND EXISTS (
            SELECT 1
            FROM trial_identities AS identity
            JOIN experiments AS experiment
              ON experiment.data_snapshot_artifact_id = identity.data_snapshot_artifact_id
             AND experiment.experiment_run_artifact_id = NEW.evidence_artifact_id
             AND experiment.code_sha256 = identity.code_sha256
             AND experiment.config_sha256 = identity.config_sha256
            JOIN trials AS source_trial
              ON source_trial.trial_id = experiment.trial_id
             AND source_trial.strategy_family_id = identity.strategy_family_id
            JOIN experiment_registry AS registry
              ON registry.experiment_id = experiment.experiment_id
            JOIN artifacts AS evidence
              ON evidence.artifact_id = NEW.evidence_artifact_id
             AND evidence.artifact_type = 'ExperimentRun'
            JOIN relations AS relation
              ON relation.parent_artifact_id = identity.data_snapshot_artifact_id
             AND relation.child_artifact_id = NEW.evidence_artifact_id
             AND relation.relation_type = 'derives_from'
            WHERE identity.trial_id = NEW.trial_id
              AND registry.strategy_family_id = identity.strategy_family_id
              AND registry.dataset_sha256 = identity.dataset_sha256
              AND registry.code_sha256 = identity.code_sha256
              AND registry.config_sha256 = identity.config_sha256
        )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'trial stage requires immutable evidence bound to the trial inputs');
END;

CREATE TRIGGER IF NOT EXISTS trial_stage_transitions_require_order
BEFORE INSERT ON trial_stage_transitions
FOR EACH ROW
WHEN NOT (
    (
        NEW.from_stage IS NULL
        AND NEW.to_stage = 'EXPLORATORY'
        AND NOT EXISTS (
            SELECT 1 FROM trial_stage_transitions WHERE trial_id = NEW.trial_id
        )
    )
    OR (
        NEW.from_stage = 'EXPLORATORY'
        AND NEW.to_stage = 'CANDIDATE'
        AND EXISTS (
            SELECT 1 FROM trial_stage_transitions
            WHERE trial_id = NEW.trial_id AND to_stage = 'EXPLORATORY'
        )
        AND NOT EXISTS (
            SELECT 1 FROM trial_stage_transitions
            WHERE trial_id = NEW.trial_id AND to_stage = 'CANDIDATE'
        )
    )
    OR (
        NEW.from_stage = 'CANDIDATE'
        AND NEW.to_stage = 'PROMOTABLE'
        AND EXISTS (
            SELECT 1 FROM trial_stage_transitions
            WHERE trial_id = NEW.trial_id AND to_stage = 'CANDIDATE'
        )
        AND NOT EXISTS (
            SELECT 1 FROM trial_stage_transitions
            WHERE trial_id = NEW.trial_id AND to_stage = 'PROMOTABLE'
        )
    )
    OR (
        NEW.from_stage = 'PROMOTABLE'
        AND NEW.to_stage = 'LIVE_CANDIDATE'
        AND EXISTS (
            SELECT 1 FROM trial_stage_transitions
            WHERE trial_id = NEW.trial_id AND to_stage = 'PROMOTABLE'
        )
        AND NOT EXISTS (
            SELECT 1 FROM trial_stage_transitions
            WHERE trial_id = NEW.trial_id AND to_stage = 'LIVE_CANDIDATE'
        )
    )
)
BEGIN
    SELECT RAISE(ABORT, 'trial stage transition order is invalid');
END;

CREATE TRIGGER IF NOT EXISTS trial_stage_transitions_reject_holdout_violation
BEFORE INSERT ON trial_stage_transitions
FOR EACH ROW
WHEN NEW.to_stage IN ('CANDIDATE', 'PROMOTABLE', 'LIVE_CANDIDATE')
 AND EXISTS (
    SELECT 1 FROM holdout_accesses WHERE trial_id = NEW.trial_id
)
BEGIN
    SELECT RAISE(ABORT, 'holdout access blocks candidate-or-higher promotion');
END;

CREATE TRIGGER IF NOT EXISTS trial_stage_transitions_no_replace
BEFORE INSERT ON trial_stage_transitions
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM trial_stage_transitions
    WHERE stage_transition_id = NEW.stage_transition_id
       OR (trial_id = NEW.trial_id AND to_stage = NEW.to_stage)
)
BEGIN
    SELECT RAISE(ABORT, 'trial stage transition replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trial_stage_transitions_no_update
BEFORE UPDATE ON trial_stage_transitions
BEGIN
    SELECT RAISE(ABORT, 'trial stage transitions are append-only');
END;

CREATE TRIGGER IF NOT EXISTS trial_stage_transitions_no_delete
BEFORE DELETE ON trial_stage_transitions
BEGIN
    SELECT RAISE(ABORT, 'physical trial stage purge is forbidden');
END;
