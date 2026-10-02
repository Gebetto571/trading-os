CREATE TABLE IF NOT EXISTS overfitting_assessments (
    assessment_id TEXT PRIMARY KEY CHECK (
        length(assessment_id) = 64 AND assessment_id NOT GLOB '*[^0-9a-f]*'
    ),
    trial_id TEXT NOT NULL REFERENCES trial_identities(trial_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    evidence_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    trial_count INTEGER NOT NULL CHECK (trial_count >= 1),
    policy_sha256 TEXT NOT NULL CHECK (
        length(policy_sha256) = 64 AND policy_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    canonical_evidence_json TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (
        length(evidence_sha256) = 64 AND evidence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    recorded_at_ns INTEGER NOT NULL CHECK (recorded_at_ns >= 0),
    passed INTEGER NOT NULL CHECK (passed = 1),
    UNIQUE (trial_id, evidence_artifact_id),
    UNIQUE (trial_id, evidence_artifact_id, evidence_sha256, recorded_at_ns)
);

-- The registry connection supplies this deterministic local function.  A raw
-- SQLite connection cannot manufacture an assessment row: its insert fails
-- closed before a candidate-or-higher transition can observe the row.
CREATE TRIGGER IF NOT EXISTS overfitting_assessments_require_canonical_hash
BEFORE INSERT ON overfitting_assessments
FOR EACH ROW
WHEN NEW.evidence_sha256 <> research_engine_sha256(NEW.canonical_evidence_json)
BEGIN
    SELECT RAISE(ABORT, 'overfitting assessment canonical evidence hash does not match');
END;

CREATE TRIGGER IF NOT EXISTS overfitting_assessments_require_trial_bound_evidence
BEFORE INSERT ON overfitting_assessments
FOR EACH ROW
WHEN NOT EXISTS (
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
BEGIN
    SELECT RAISE(ABORT, 'overfitting assessment requires immutable evidence bound to the trial inputs');
END;

CREATE TRIGGER IF NOT EXISTS overfitting_assessments_reject_holdout_access
BEFORE INSERT ON overfitting_assessments
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM holdout_accesses WHERE trial_id = NEW.trial_id
)
BEGIN
    SELECT RAISE(ABORT, 'holdout access blocks overfitting assessment');
END;

CREATE TRIGGER IF NOT EXISTS overfitting_assessments_no_replace
BEFORE INSERT ON overfitting_assessments
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM overfitting_assessments
    WHERE assessment_id = NEW.assessment_id
       OR (trial_id = NEW.trial_id AND evidence_artifact_id = NEW.evidence_artifact_id)
       OR (
            trial_id = NEW.trial_id
            AND evidence_artifact_id = NEW.evidence_artifact_id
            AND evidence_sha256 = NEW.evidence_sha256
            AND recorded_at_ns = NEW.recorded_at_ns
       )
)
BEGIN
    SELECT RAISE(ABORT, 'overfitting assessment replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS overfitting_assessments_no_update
BEFORE UPDATE ON overfitting_assessments
BEGIN
    SELECT RAISE(ABORT, 'overfitting assessments are immutable');
END;

CREATE TRIGGER IF NOT EXISTS overfitting_assessments_no_delete
BEFORE DELETE ON overfitting_assessments
BEGIN
    SELECT RAISE(ABORT, 'physical overfitting assessment purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS trial_stage_transitions_require_overfitting_assessment
BEFORE INSERT ON trial_stage_transitions
FOR EACH ROW
WHEN NEW.to_stage IN ('CANDIDATE', 'PROMOTABLE', 'LIVE_CANDIDATE')
 AND NOT EXISTS (
    SELECT 1
    FROM overfitting_assessments AS assessment
    JOIN trial_identities AS identity
      ON identity.trial_id = NEW.trial_id
    WHERE assessment.trial_id = NEW.trial_id
      AND assessment.evidence_artifact_id = NEW.evidence_artifact_id
      AND assessment.passed = 1
      AND assessment.trial_count = (
          SELECT COUNT(*)
          FROM trial_identities AS sibling
          WHERE sibling.strategy_family_id = identity.strategy_family_id
            AND sibling.data_snapshot_artifact_id = identity.data_snapshot_artifact_id
            AND sibling.dataset_sha256 = identity.dataset_sha256
      )
)
BEGIN
    SELECT RAISE(ABORT, 'candidate-or-higher stage requires a matching passed overfitting assessment');
END;
