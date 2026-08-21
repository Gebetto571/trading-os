CREATE TABLE IF NOT EXISTS h1_raw_lineage_evidence (
    opaque_evidence_sha256 TEXT PRIMARY KEY CHECK (
        length(opaque_evidence_sha256) = 64
        AND opaque_evidence_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    raw_bytes BLOB NOT NULL CHECK (
        typeof(raw_bytes) = 'blob' AND length(raw_bytes) > 0
    ),
    c3_task_uuid TEXT NOT NULL,
    -- One immutable C3 result is one source identity.  A distinct BLOB must
    -- never be attached to that same result through a second H1 lineage.
    c3_result_uuid TEXT NOT NULL UNIQUE,
    c3_result_raw_sha256 TEXT NOT NULL CHECK (
        length(c3_result_raw_sha256) = 64
        AND c3_result_raw_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    c3_exporter_commit TEXT NOT NULL CHECK (
        length(c3_exporter_commit) = 40
        AND c3_exporter_commit NOT GLOB '*[^0-9a-f]*'
    ),
    c2_canonical_wire_sha256 TEXT NOT NULL CHECK (
        length(c2_canonical_wire_sha256) = 64
        AND c2_canonical_wire_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    c2_materialization_id TEXT NOT NULL CHECK (
        length(c2_materialization_id) = 64
        AND c2_materialization_id NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0)
);

CREATE TABLE IF NOT EXISTS h1_lineage_materializations (
    lineage_id TEXT PRIMARY KEY CHECK (
        length(lineage_id) = 64 AND lineage_id NOT GLOB '*[^0-9a-f]*'
    ),
    opaque_evidence_sha256 TEXT NOT NULL UNIQUE
        REFERENCES h1_raw_lineage_evidence(opaque_evidence_sha256)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    data_snapshot_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    experiment_run_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    strategy_candidate_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    strategy_package_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    replay_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    paper_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    decision_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    c0_data_snapshot_id TEXT NOT NULL CHECK (
        length(c0_data_snapshot_id) = 64 AND c0_data_snapshot_id NOT GLOB '*[^0-9a-f]*'
    ),
    c0_experiment_run_id TEXT NOT NULL CHECK (
        length(c0_experiment_run_id) = 64 AND c0_experiment_run_id NOT GLOB '*[^0-9a-f]*'
    ),
    c0_candidate_id TEXT NOT NULL CHECK (
        length(c0_candidate_id) = 64 AND c0_candidate_id NOT GLOB '*[^0-9a-f]*'
    ),
    c0_package_id TEXT NOT NULL CHECK (
        length(c0_package_id) = 64 AND c0_package_id NOT GLOB '*[^0-9a-f]*'
    ),
    c0_trace_id TEXT NOT NULL CHECK (
        length(c0_trace_id) = 64 AND c0_trace_id NOT GLOB '*[^0-9a-f]*'
    ),
    c0_strategy_family_id TEXT NOT NULL CHECK (length(c0_strategy_family_id) > 0),
    c0_code_sha256 TEXT NOT NULL CHECK (
        length(c0_code_sha256) = 64 AND c0_code_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    c0_config_sha256 TEXT NOT NULL CHECK (
        length(c0_config_sha256) = 64 AND c0_config_sha256 NOT GLOB '*[^0-9a-f]*'
    ),
    created_at_ns INTEGER NOT NULL CHECK (created_at_ns >= 0)
);

-- Raw connections do not have this deterministic local function and therefore
-- fail closed before they can manufacture an opaque-evidence row.
CREATE TRIGGER IF NOT EXISTS h1_raw_lineage_evidence_require_blob_hash
BEFORE INSERT ON h1_raw_lineage_evidence
FOR EACH ROW
WHEN NEW.opaque_evidence_sha256 <> research_engine_blob_sha256(NEW.raw_bytes)
BEGIN
    SELECT RAISE(ABORT, 'H1 opaque evidence SHA-256 does not match its raw bytes');
END;

CREATE TRIGGER IF NOT EXISTS h1_raw_lineage_evidence_no_replace
BEFORE INSERT ON h1_raw_lineage_evidence
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM h1_raw_lineage_evidence
    WHERE opaque_evidence_sha256 = NEW.opaque_evidence_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'H1 opaque evidence replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS h1_raw_lineage_evidence_no_update
BEFORE UPDATE ON h1_raw_lineage_evidence
BEGIN
    SELECT RAISE(ABORT, 'H1 opaque evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS h1_raw_lineage_evidence_no_delete
BEFORE DELETE ON h1_raw_lineage_evidence
BEGIN
    SELECT RAISE(ABORT, 'physical H1 opaque evidence purge is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS h1_lineage_materializations_require_chain
BEFORE INSERT ON h1_lineage_materializations
FOR EACH ROW
WHEN NOT (
    EXISTS (
        SELECT 1 FROM h1_raw_lineage_evidence
        WHERE opaque_evidence_sha256 = NEW.opaque_evidence_sha256
    )
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.data_snapshot_artifact_id) = 'DataSnapshot'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.experiment_run_artifact_id) = 'ExperimentRun'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.strategy_candidate_artifact_id) = 'StrategyCandidate'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.strategy_package_artifact_id) = 'StrategyPackage'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.replay_artifact_id) = 'Replay'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.paper_artifact_id) = 'Paper'
    AND (SELECT artifact_type FROM artifacts WHERE artifact_id = NEW.decision_artifact_id) = 'Decision'
    AND EXISTS (
        SELECT 1 FROM relations
        WHERE parent_artifact_id = NEW.data_snapshot_artifact_id
          AND child_artifact_id = NEW.experiment_run_artifact_id
          AND relation_type = 'derives_from'
    )
    AND EXISTS (
        SELECT 1 FROM relations
        WHERE parent_artifact_id = NEW.experiment_run_artifact_id
          AND child_artifact_id = NEW.strategy_candidate_artifact_id
          AND relation_type = 'derives_from'
    )
    AND EXISTS (
        SELECT 1 FROM relations
        WHERE parent_artifact_id = NEW.strategy_candidate_artifact_id
          AND child_artifact_id = NEW.strategy_package_artifact_id
          AND relation_type = 'derives_from'
    )
    AND EXISTS (
        SELECT 1 FROM relations
        WHERE parent_artifact_id = NEW.strategy_package_artifact_id
          AND child_artifact_id = NEW.replay_artifact_id
          AND relation_type = 'derives_from'
    )
    AND EXISTS (
        SELECT 1 FROM relations
        WHERE parent_artifact_id = NEW.replay_artifact_id
          AND child_artifact_id = NEW.paper_artifact_id
          AND relation_type = 'derives_from'
    )
    AND EXISTS (
        SELECT 1 FROM relations
        WHERE parent_artifact_id = NEW.paper_artifact_id
          AND child_artifact_id = NEW.decision_artifact_id
          AND relation_type = 'derives_from'
    )
)
BEGIN
    SELECT RAISE(ABORT, 'H1 materialization requires one complete adjacent lineage chain');
END;

CREATE TRIGGER IF NOT EXISTS h1_lineage_materializations_no_replace
BEFORE INSERT ON h1_lineage_materializations
FOR EACH ROW
WHEN EXISTS (
    SELECT 1 FROM h1_lineage_materializations
    WHERE lineage_id = NEW.lineage_id
       OR opaque_evidence_sha256 = NEW.opaque_evidence_sha256
)
BEGIN
    SELECT RAISE(ABORT, 'H1 lineage materialization replacement is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS h1_lineage_materializations_no_update
BEFORE UPDATE ON h1_lineage_materializations
BEGIN
    SELECT RAISE(ABORT, 'H1 lineage materialization is immutable');
END;

CREATE TRIGGER IF NOT EXISTS h1_lineage_materializations_no_delete
BEFORE DELETE ON h1_lineage_materializations
BEGIN
    SELECT RAISE(ABORT, 'physical H1 lineage purge is forbidden');
END;
