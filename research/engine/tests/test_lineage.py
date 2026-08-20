"""A1/H0 lineage, migration, and immutable SQLite acceptance tests."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from research_engine.errors import RegistryConflict
from research_engine.hashing import canonical_bytes, sha256_bytes, sha256_file
from research_engine.overfitting import (
    CscvPartition,
    DEFAULT_POLICY,
    OverfittingEvidence,
    RegimeScore,
    WalkForwardFold,
)
from research_engine.registry import ExperimentRegistry, LineageArtifact
from research_engine.runner import run_experiment


FIXTURE = ENGINE_ROOT / "fixtures" / "candles_v1.parquet"
MIGRATION = ENGINE_ROOT / "migrations" / "001_experiment_registry.sql"
MARKER = ".research-engine-disposable-lineage-fixture"
MARKER_CONTENT = "research-engine-disposable-lineage-fixture-v1\n"


def digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def artifact(artifact_type: str, identity: str, content: str, label: str) -> LineageArtifact:
    return LineageArtifact(
        artifact_type=artifact_type,
        identity_sha256=digest(identity),
        content_sha256=digest(content),
        payload={"contract_label": label},
    )


def passing_overfitting_evidence() -> OverfittingEvidence:
    """A compact deterministic proof used only to preserve D0 stage coverage."""
    return OverfittingEvidence(
        policy=DEFAULT_POLICY,
        walk_forward_folds=(
            WalkForwardFold(0, 10, 12, 20, 22, 30, 2, 2, 12, 10),
            WalkForwardFold(10, 20, 22, 30, 32, 40, 2, 2, 12, 10),
            WalkForwardFold(20, 30, 32, 40, 42, 50, 2, 2, 12, 10),
        ),
        raw_p_value_ppm=10_000,
        cscv_partitions=(
            CscvPartition((12, 8), (12, 8)),
            CscvPartition((8, 12), (8, 12)),
        ),
        regime_scores=(
            RegimeScore("BULL", 8),
            RegimeScore("RANGE", 7),
            RegimeScore("BEAR", 6),
        ),
        center_oos_score_bps=10,
        neighbor_oos_scores_bps=(7, 8),
        baseline_cost_bps=5,
        stressed_cost_bps=10,
        stressed_oos_score_bps=4,
    )


class LineageAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "lineage.sqlite3"
        self.registry = ExperimentRegistry(self.database, MIGRATION)
        self.registry.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _count(self, table: str) -> int:
        connection = sqlite3.connect(self.database)
        try:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()

    def _d0_evidence(
        self,
        label: str,
        *,
        dataset_label: str,
        strategy_family_id: str,
        code_sha256: str,
        config_sha256: str,
    ) -> tuple[LineageArtifact, LineageArtifact]:
        """Create completed A0 evidence that is bound to exact D0 trial inputs."""
        dataset_identity = digest(f"{dataset_label}-identity")
        dataset_sha256 = digest(f"{dataset_label}-content")
        experiment_id = digest(f"{label}-experiment")
        canonical_summary = {"d0_test_result": label}
        result_artifact_id = sha256_bytes(canonical_bytes(canonical_summary))
        self.registry.record_or_reuse(
            experiment_id=experiment_id,
            trial_id=f"{label}-source-trial",
            strategy_family_id=strategy_family_id,
            dataset_path=f"/readonly/{dataset_label}.parquet",
            dataset_identity=dataset_identity,
            dataset_sha256=dataset_sha256,
            code_sha256=code_sha256,
            config_sha256=config_sha256,
            started_at_ns=1,
            finished_at_ns=2,
            result_artifact_id=result_artifact_id,
            canonical_summary=canonical_summary,
        )
        snapshot = LineageArtifact(
            artifact_type="DataSnapshot",
            identity_sha256=dataset_identity,
            content_sha256=dataset_sha256,
            payload={
                "dataset_identity": dataset_identity,
                "dataset_sha256": dataset_sha256,
            },
        )
        experiment = LineageArtifact(
            artifact_type="ExperimentRun",
            identity_sha256=experiment_id,
            content_sha256=result_artifact_id,
            payload={
                "code_sha256": code_sha256,
                "config_sha256": config_sha256,
                "dataset_identity": dataset_identity,
                "dataset_sha256": dataset_sha256,
                "experiment_id": experiment_id,
                "result_artifact_id": result_artifact_id,
                "strategy_family_id": strategy_family_id,
                "trial_id": f"{label}-source-trial",
            },
        )
        return snapshot, experiment

    def test_contract_bundle_is_idempotent_and_invalid_edges_roll_back_atomically(self) -> None:
        snapshot = artifact("DataSnapshot", "snapshot-1", "dataset-1", "snapshot")
        experiment = artifact("ExperimentRun", "experiment-1", "result-1", "experiment")
        candidate = artifact("StrategyCandidate", "candidate-1", "candidate-1", "candidate-contract")

        with self.assertRaises(RegistryConflict):
            self.registry.record_contract_bundle(
                (snapshot, candidate),
                ((snapshot.artifact_id, candidate.artifact_id),),
            )
        self.assertEqual(self._count("artifacts"), 0)
        self.assertEqual(self._count("relations"), 0)

        with self.assertRaises(RegistryConflict):
            self.registry.record_contract_bundle(
                (snapshot,),
                ((snapshot.artifact_id, digest("missing-parent")),),
            )
        self.assertEqual(self._count("artifacts"), 0)

        with self.assertRaises(RegistryConflict):
            self.registry.record_contract_bundle(
                (snapshot,),
                ((snapshot.artifact_id, snapshot.artifact_id),),
            )
        self.assertEqual(self._count("artifacts"), 0)

        first = self.registry.record_contract_bundle(
            (snapshot, experiment),
            ((snapshot.artifact_id, experiment.artifact_id),),
        )
        second = self.registry.record_contract_bundle(
            (snapshot, experiment),
            ((snapshot.artifact_id, experiment.artifact_id),),
        )
        self.assertFalse(first.reused)
        self.assertTrue(second.reused)
        self.assertGreater(first.sqlite_write_elapsed_ns, 0)
        self.assertGreater(second.sqlite_read_elapsed_ns, 0)
        self.assertEqual(self._count("artifacts"), 2)
        self.assertEqual(self._count("relations"), 1)

    def test_d0_trial_identity_holdout_and_stage_gate_are_immutable_and_idempotent(self) -> None:
        identity_args = {
            "strategy_family_id": "family-d0",
            "code_sha256": digest("d0-code-a"),
            "config_sha256": digest("d0-config-a"),
            "created_at_ns": 1,
        }
        snapshot, evidence = self._d0_evidence(
            "d0-a",
            dataset_label="d0",
            strategy_family_id=identity_args["strategy_family_id"],
            code_sha256=identity_args["code_sha256"],
            config_sha256=identity_args["config_sha256"],
        )
        identity_args.update(
            {
                "data_snapshot_artifact_id": snapshot.artifact_id,
                "dataset_sha256": snapshot.content_sha256,
            }
        )
        first = self.registry.record_trial_identity(**identity_args)
        replay = self.registry.record_trial_identity(**identity_args)
        second_code_sha256 = digest("d0-code-b")
        second_config_sha256 = digest("d0-config-b")
        second_snapshot, second_evidence = self._d0_evidence(
            "d0-b",
            dataset_label="d0",
            strategy_family_id=identity_args["strategy_family_id"],
            code_sha256=second_code_sha256,
            config_sha256=second_config_sha256,
        )
        self.assertEqual(second_snapshot.artifact_id, snapshot.artifact_id)
        second = self.registry.record_trial_identity(
            **{
                **identity_args,
                "code_sha256": second_code_sha256,
                "config_sha256": second_config_sha256,
                "created_at_ns": 2,
            }
        )
        self.assertFalse(first.reused)
        self.assertTrue(replay.reused)
        self.assertEqual(first.trial_id, replay.trial_id)
        self.assertEqual(first.trial_count, 1)
        self.assertEqual(replay.trial_count, 1)
        self.assertEqual(second.trial_count, 2)
        self.assertNotEqual(first.trial_id, second.trial_id)
        self.assertEqual(self._count("trial_identities"), 2)
        self.assertEqual(self._count("trial_stage_transitions"), 2)

        with self.assertRaises(RegistryConflict):
            self.registry.record_trial_identity(
                **{
                    **identity_args,
                    "data_snapshot_artifact_id": digest("missing-snapshot"),
                    "created_at_ns": 3,
                }
            )
        self.assertEqual(self._count("trial_identities"), 2)

        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=first.trial_id,
                to_stage="PROMOTABLE",
                evidence_artifact_id=evidence.artifact_id,
                recorded_at_ns=4,
            )
        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=first.trial_id,
                to_stage="CANDIDATE",
                evidence_artifact_id=second_evidence.artifact_id,
                recorded_at_ns=4,
            )
        raw_connection = sqlite3.connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT INTO trial_stage_transitions (
                        stage_transition_id, trial_id, from_stage, to_stage,
                        evidence_artifact_id, recorded_at_ns
                    ) VALUES (?, ?, 'EXPLORATORY', 'CANDIDATE', ?, 4)
                    """,
                    (
                        digest("raw-unbound-stage-evidence"),
                        second.trial_id,
                        evidence.artifact_id,
                    ),
                )
        finally:
            raw_connection.close()
        assessment = self.registry.record_overfitting_assessment(
            trial_id=first.trial_id,
            evidence_artifact_id=evidence.artifact_id,
            evidence=passing_overfitting_evidence(),
            recorded_at_ns=5,
        )
        self.assertEqual(assessment.trial_count, 2)
        candidate = self.registry.advance_trial_stage(
            trial_id=first.trial_id,
            to_stage="CANDIDATE",
            evidence_artifact_id=evidence.artifact_id,
            recorded_at_ns=5,
        )
        candidate_replay = self.registry.advance_trial_stage(
            trial_id=first.trial_id,
            to_stage="CANDIDATE",
            evidence_artifact_id=evidence.artifact_id,
            recorded_at_ns=5,
        )
        promotable = self.registry.advance_trial_stage(
            trial_id=first.trial_id,
            to_stage="PROMOTABLE",
            evidence_artifact_id=evidence.artifact_id,
            recorded_at_ns=6,
        )
        live = self.registry.advance_trial_stage(
            trial_id=first.trial_id,
            to_stage="LIVE_CANDIDATE",
            evidence_artifact_id=evidence.artifact_id,
            recorded_at_ns=7,
        )
        self.assertFalse(candidate.reused)
        self.assertTrue(candidate_replay.reused)
        self.assertEqual(candidate.stage_transition_id, candidate_replay.stage_transition_id)
        self.assertEqual((promotable.stage, live.stage), ("PROMOTABLE", "LIVE_CANDIDATE"))

        with self.assertRaises(RegistryConflict):
            self.registry.record_holdout_access(
                trial_id=first.trial_id,
                evidence_artifact_id=snapshot.artifact_id,
                accessed_at_ns=8,
            )

        with self.assertRaises(RegistryConflict):
            self.registry.record_holdout_access(
                trial_id=second.trial_id,
                evidence_artifact_id=second_evidence.artifact_id,
                accessed_at_ns=8,
            )
        access = self.registry.record_holdout_access(
            trial_id=second.trial_id,
            evidence_artifact_id=snapshot.artifact_id,
            accessed_at_ns=8,
        )
        access_replay = self.registry.record_holdout_access(
            trial_id=second.trial_id,
            evidence_artifact_id=snapshot.artifact_id,
            accessed_at_ns=8,
        )
        self.assertFalse(access.reused)
        self.assertTrue(access_replay.reused)
        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=second.trial_id,
                to_stage="CANDIDATE",
                evidence_artifact_id=evidence.artifact_id,
                recorded_at_ns=9,
            )
        self.assertEqual(self._count("holdout_accesses"), 1)

        connection = sqlite3.connect(self.database)
        try:
            post_candidate_holdout_id = sha256_bytes(
                canonical_bytes(
                    {
                        "accessed_at_ns": 10,
                        "evidence_artifact_id": snapshot.artifact_id,
                        "trial_id": first.trial_id,
                    }
                )
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO holdout_accesses (
                        holdout_access_id, trial_id, evidence_artifact_id, accessed_at_ns
                    ) VALUES (?, ?, ?, 10)
                    """,
                    (post_candidate_holdout_id, first.trial_id, snapshot.artifact_id),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                "UPDATE holdout_accesses SET accessed_at_ns = 99 WHERE holdout_access_id = ?",
                (access.holdout_access_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM holdout_accesses WHERE holdout_access_id = ?",
                    (access.holdout_access_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO trial_stage_transitions (
                        stage_transition_id, trial_id, from_stage, to_stage,
                        evidence_artifact_id, recorded_at_ns
                    ) VALUES (?, ?, 'EXPLORATORY', 'CANDIDATE', ?, 10)
                    """,
                    (digest("blocked-raw-transition"), second.trial_id, second_evidence.artifact_id),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT OR REPLACE INTO trial_identities (
                        trial_id, strategy_family_id, data_snapshot_artifact_id,
                        dataset_sha256, code_sha256, config_sha256, identity_sha256,
                        created_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        first.trial_id,
                        identity_args["strategy_family_id"],
                        snapshot.artifact_id,
                        snapshot.content_sha256,
                        identity_args["code_sha256"],
                        identity_args["config_sha256"],
                        first.trial_id,
                    ),
                )
        finally:
            connection.close()
        self.assertEqual(self._count("trial_identities"), 2)
        self.assertEqual(self._count("holdout_accesses"), 1)
        self.assertEqual(self._count("trial_stage_transitions"), 5)

        same_identity_changed_hash = LineageArtifact(
            artifact_type="DataSnapshot",
            identity_sha256=snapshot.identity_sha256,
            content_sha256=digest("dataset-2"),
            payload={"contract_label": "snapshot"},
        )
        with self.assertRaises(RegistryConflict):
            self.registry.record_contract_bundle((same_identity_changed_hash,), ())
        self.assertEqual(self._count("artifacts"), 3)
        self.assertEqual(self._count("relations"), 2)

    def test_result_hash_mismatch_is_rejected_without_a_partial_experiment(self) -> None:
        with self.assertRaises(RegistryConflict):
            self.registry.record_or_reuse(
                experiment_id=digest("experiment-hash-mismatch"),
                trial_id="hash-mismatch-trial",
                strategy_family_id="deterministic-event-study-v1",
                dataset_path="/readonly/dataset.parquet",
                dataset_identity=digest("dataset-identity"),
                dataset_sha256=digest("dataset-content"),
                code_sha256=digest("code"),
                config_sha256=digest("config"),
                started_at_ns=1,
                finished_at_ns=2,
                result_artifact_id=digest("not-the-canonical-summary"),
                canonical_summary={"result": "canonical"},
            )
        self.assertEqual(self._count("experiment_registry"), 0)
        self.assertEqual(self._count("artifacts"), 0)
        self.assertEqual(self._count("experiments"), 0)

    def test_relocated_identical_data_reuses_its_snapshot_without_lineage_conflict(self) -> None:
        dataset_identity = digest("relocated-dataset-identity")
        dataset_sha256 = digest("relocated-dataset-content")
        code_sha256 = digest("relocated-code")
        first_summary = {"experiment": "first-location"}
        second_summary = {"experiment": "second-location"}

        first = self.registry.record_or_reuse(
            experiment_id=digest("relocated-experiment-one"),
            trial_id="relocated-trial",
            strategy_family_id="deterministic-event-study-v1",
            dataset_path="/readonly/first-location.parquet",
            dataset_identity=dataset_identity,
            dataset_sha256=dataset_sha256,
            code_sha256=code_sha256,
            config_sha256=digest("relocated-config-one"),
            started_at_ns=1,
            finished_at_ns=2,
            result_artifact_id=sha256_bytes(canonical_bytes(first_summary)),
            canonical_summary=first_summary,
        )
        second = self.registry.record_or_reuse(
            experiment_id=digest("relocated-experiment-two"),
            trial_id="relocated-trial",
            strategy_family_id="deterministic-event-study-v1",
            dataset_path="/readonly/second-location.parquet",
            dataset_identity=dataset_identity,
            dataset_sha256=dataset_sha256,
            code_sha256=code_sha256,
            config_sha256=digest("relocated-config-two"),
            started_at_ns=3,
            finished_at_ns=4,
            result_artifact_id=sha256_bytes(canonical_bytes(second_summary)),
            canonical_summary=second_summary,
        )

        self.assertFalse(first.reused)
        self.assertFalse(second.reused)
        self.assertEqual(
            self._count_type("DataSnapshot"),
            1,
        )
        self.assertEqual(self._count_type("ExperimentRun"), 2)
        self.assertEqual(self._count("relations"), 2)

    def _count_type(self, artifact_type: str) -> int:
        connection = sqlite3.connect(self.database)
        try:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM artifacts WHERE artifact_type = ?",
                    (artifact_type,),
                ).fetchone()[0]
            )
        finally:
            connection.close()

    def test_declared_full_lineage_chain_is_a_contract_without_future_producers(self) -> None:
        artifact_types = (
            "DataSnapshot",
            "ExperimentRun",
            "StrategyCandidate",
            "StrategyPackage",
            "Replay",
            "Paper",
            "Decision",
        )
        artifacts = tuple(
            artifact(
                artifact_type,
                f"{artifact_type}-identity",
                f"{artifact_type}-content",
                artifact_type,
            )
            for artifact_type in artifact_types
        )
        result = self.registry.record_contract_bundle(
            artifacts,
            tuple(
                (parent.artifact_id, child.artifact_id)
                for parent, child in zip(artifacts, artifacts[1:])
            ),
        )
        self.assertFalse(result.reused)
        self.assertEqual(len(result.artifact_ids), len(artifact_types))
        self.assertEqual(self._count("artifacts"), len(artifact_types))
        self.assertEqual(self._count("relations"), len(artifact_types) - 1)
        self.assertEqual(self._count("promotions"), 0)

    def test_foreign_keys_and_immutability_are_enforced_by_registry_connections(self) -> None:
        snapshot = artifact("DataSnapshot", "snapshot-2", "dataset-2", "snapshot")
        experiment = artifact("ExperimentRun", "experiment-2", "result-2", "experiment")
        self.registry.record_contract_bundle(
            (snapshot, experiment),
            ((snapshot.artifact_id, experiment.artifact_id),),
        )
        summary = {"result": "immutable-registry-record"}
        self.registry.record_or_reuse(
            experiment_id=digest("immutable-registry-experiment"),
            trial_id="immutable-registry-trial",
            strategy_family_id="deterministic-event-study-v1",
            dataset_path="/readonly/immutable-registry.parquet",
            dataset_identity=digest("immutable-registry-dataset-identity"),
            dataset_sha256=digest("immutable-registry-dataset-content"),
            code_sha256=digest("immutable-registry-code"),
            config_sha256=digest("immutable-registry-config"),
            started_at_ns=1,
            finished_at_ns=2,
            result_artifact_id=sha256_bytes(canonical_bytes(summary)),
            canonical_summary=summary,
        )

        connection = self.registry._connect()
        try:
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO relations (parent_artifact_id, child_artifact_id, relation_type, created_at_ns)
                    VALUES (?, ?, 'derives_from', 1)
                    """,
                    (digest("missing-parent"), digest("missing-child")),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE artifacts SET content_sha256 = ? WHERE artifact_id = ?",
                    (digest("tampered"), snapshot.artifact_id),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM artifacts WHERE artifact_id = ?",
                    (snapshot.artifact_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE experiment_registry SET dataset_sha256 = ?",
                    (digest("tampered-registry-hash"),),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM experiment_registry")
        finally:
            connection.close()

        raw_connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(raw_connection.execute("PRAGMA foreign_keys").fetchone()[0], 0)
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT INTO relations (parent_artifact_id, child_artifact_id, relation_type, created_at_ns)
                    VALUES (?, ?, 'derives_from', 1)
                    """,
                    (digest("raw-missing-parent"), digest("raw-missing-child")),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT INTO relations (parent_artifact_id, child_artifact_id, relation_type, created_at_ns)
                    VALUES (?, ?, 'derives_from', 1)
                    """,
                    (experiment.artifact_id, snapshot.artifact_id),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT INTO experiments (
                        experiment_id, trial_id, data_snapshot_artifact_id,
                        experiment_run_artifact_id, code_sha256, config_sha256,
                        result_artifact_id, created_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        digest("raw-missing-experiment"),
                        "raw-missing-trial",
                        digest("raw-missing-snapshot"),
                        digest("raw-missing-run"),
                        digest("raw-code"),
                        digest("raw-config"),
                        digest("raw-result"),
                    ),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT INTO promotions (
                        promotion_id, source_artifact_id, target_artifact_id,
                        decision_artifact_id, promotion_sha256, created_at_ns
                    ) VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        digest("raw-promotion"),
                        digest("raw-source"),
                        digest("raw-target"),
                        digest("raw-decision"),
                        digest("raw-promotion-hash"),
                    ),
                )
            original_snapshot = raw_connection.execute(
                "SELECT content_sha256 FROM artifacts WHERE artifact_id = ?",
                (snapshot.artifact_id,),
            ).fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT OR REPLACE INTO artifacts (
                        artifact_id, artifact_type, identity_sha256, content_sha256,
                        canonical_payload_json, created_at_ns
                    ) VALUES (?, 'DataSnapshot', ?, ?, '{}', 2)
                    """,
                    (
                        snapshot.artifact_id,
                        snapshot.identity_sha256,
                        digest("raw-replacement-content"),
                    ),
                )
            self.assertEqual(
                raw_connection.execute(
                    "SELECT content_sha256 FROM artifacts WHERE artifact_id = ?",
                    (snapshot.artifact_id,),
                ).fetchone()[0],
                original_snapshot,
            )
            original_registry_hash = raw_connection.execute(
                "SELECT dataset_sha256 FROM experiment_registry"
            ).fetchone()[0]
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT OR REPLACE INTO experiment_registry (
                        experiment_id, trial_id, strategy_family_id, dataset_path,
                        dataset_identity, dataset_sha256, code_sha256, config_sha256,
                        started_at_ns, finished_at_ns, status, result_artifact_id,
                        canonical_summary_json
                    ) VALUES (?, 'raw-replacement-trial', 'raw-family', '/readonly/raw.parquet',
                              ?, ?, ?, ?, 1, 2, 'completed', ?, '{}')
                    """,
                    (
                        digest("immutable-registry-experiment"),
                        digest("raw-identity"),
                        digest("raw-dataset"),
                        digest("raw-code"),
                        digest("raw-config"),
                        digest("raw-result"),
                    ),
                )
            existing_registry = raw_connection.execute(
                """
                SELECT trial_id, strategy_family_id, dataset_path, dataset_identity,
                       dataset_sha256, code_sha256, config_sha256, started_at_ns,
                       finished_at_ns, status, result_artifact_id, canonical_summary_json
                FROM experiment_registry
                """
            ).fetchone()
            with self.assertRaises(sqlite3.IntegrityError):
                raw_connection.execute(
                    """
                    INSERT OR REPLACE INTO experiment_registry (
                        experiment_id, trial_id, strategy_family_id, dataset_path,
                        dataset_identity, dataset_sha256, code_sha256, config_sha256,
                        started_at_ns, finished_at_ns, status, result_artifact_id,
                        canonical_summary_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (digest("raw-natural-key-replacement"), *existing_registry),
                )
            self.assertEqual(
                raw_connection.execute(
                    "SELECT dataset_sha256 FROM experiment_registry"
                ).fetchone()[0],
                original_registry_hash,
            )
        finally:
            raw_connection.close()

    def test_d0_migration_is_forward_only_in_a_marked_temporary_fixture(self) -> None:
        tables = {
            row[0]
            for row in sqlite3.connect(self.database).execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        self.assertTrue(
            {
                "schema_migrations",
                "experiment_registry",
                "artifacts",
                "relations",
                "trials",
                "experiments",
                "promotions",
                "trial_identities",
                "holdout_accesses",
                "trial_stage_transitions",
            }.issubset(tables)
        )
        (self.root / MARKER).write_text(MARKER_CONTENT, encoding="utf-8")
        before = sha256_file(self.database)
        with self.assertRaises(RegistryConflict):
            self.registry.rollback_lineage_for_disposable_fixture()
        with self.assertRaises(RegistryConflict):
            self.registry.rollback_compatibility_for_disposable_fixture()
        self.assertEqual(sha256_file(self.database), before)
        self.registry.initialize()
        self.assertEqual(sha256_file(self.database), before)

    def test_a0_runner_records_only_proven_lineage_and_observational_sqlite_latency(self) -> None:
        runtime_parent = ENGINE_ROOT / "runtime"
        runtime_parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime_parent) as temporary:
            work = Path(temporary)
            config = work / "experiment.toml"
            config.write_text(
                "\n".join(
                    [
                        f'dataset_path = "{FIXTURE}"',
                        f'dataset_sha256 = "{sha256_file(FIXTURE)}"',
                        'runtime_dir = "runtime-data"',
                        'trial_id = "lineage-trial"',
                        'strategy_family_id = "deterministic-event-study-v1"',
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            first = run_experiment(config)
            second = run_experiment(config)

            self.assertFalse(first.reused_registry_result)
            self.assertTrue(second.reused_registry_result)
            self.assertGreater(first.telemetry["sqlite_write_elapsed_ns"], 0)
            self.assertGreater(second.telemetry["sqlite_read_elapsed_ns"], 0)
            self.assertNotIn("sqlite_write_elapsed_ns", first.canonical_summary)
            self.assertNotIn("sqlite_read_elapsed_ns", first.canonical_summary)

            database = work / "runtime-data" / "experiments.sqlite3"
            connection = sqlite3.connect(database)
            try:
                artifact_types = {
                    row[0] for row in connection.execute("SELECT artifact_type FROM artifacts")
                }
                self.assertEqual(artifact_types, {"DataSnapshot", "ExperimentRun"})
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM relations").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM trials").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM experiments").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM promotions").fetchone()[0], 0)
            finally:
                connection.close()
