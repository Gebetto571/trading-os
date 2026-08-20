"""D acceptance tests for immutable trial-count and overfitting safety gates."""

from __future__ import annotations

import ast
from dataclasses import replace
import inspect
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from research_engine.errors import RegistryConflict
from research_engine.hashing import canonical_bytes, sha256_bytes
from research_engine.overfitting import (
    CscvPartition,
    DEFAULT_POLICY,
    OverfittingEvidence,
    OverfittingValidationError,
    RegimeScore,
    WalkForwardFold,
    validate_and_canonicalize,
)
from research_engine.registry import ExperimentRegistry, LineageArtifact


MIGRATIONS = ENGINE_ROOT / "migrations"


def digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


class OverfittingSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "overfitting.sqlite3"
        self.registry = ExperimentRegistry(self.database, MIGRATIONS)
        self.registry.initialize()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _count(self, table: str) -> int:
        connection = sqlite3.connect(self.database)
        try:
            return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            connection.close()

    def _bound_trial(
        self,
        label: str,
        *,
        family: str = "family-d-overfitting",
        dataset_label: str = "dataset-d-overfitting",
        code_label: str | None = None,
        config_label: str | None = None,
        identity_created_at_ns: int = 3,
    ) -> tuple[object, LineageArtifact, LineageArtifact]:
        """Create a completed A0 run then bind one D0 trial to it."""
        dataset_identity = digest(f"{dataset_label}-identity")
        dataset_sha256 = digest(f"{dataset_label}-content")
        code_sha256 = digest(code_label or f"{label}-code")
        config_sha256 = digest(config_label or f"{label}-config")
        experiment_id = digest(f"{label}-experiment")
        summary = {"d_overfitting_result": label}
        result_artifact_id = sha256_bytes(canonical_bytes(summary))
        self.registry.record_or_reuse(
            experiment_id=experiment_id,
            trial_id=f"{label}-source-trial",
            strategy_family_id=family,
            dataset_path=f"/readonly/{dataset_label}.parquet",
            dataset_identity=dataset_identity,
            dataset_sha256=dataset_sha256,
            code_sha256=code_sha256,
            config_sha256=config_sha256,
            started_at_ns=1,
            finished_at_ns=2,
            result_artifact_id=result_artifact_id,
            canonical_summary=summary,
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
        run = LineageArtifact(
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
                "strategy_family_id": family,
                "trial_id": f"{label}-source-trial",
            },
        )
        trial = self.registry.record_trial_identity(
            strategy_family_id=family,
            data_snapshot_artifact_id=snapshot.artifact_id,
            dataset_sha256=dataset_sha256,
            code_sha256=code_sha256,
            config_sha256=config_sha256,
            created_at_ns=identity_created_at_ns,
        )
        return trial, snapshot, run

    @staticmethod
    def _passing_evidence() -> OverfittingEvidence:
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

    def test_pure_validator_is_integer_only_canonical_and_rejects_weakened_policy(self) -> None:
        evidence = self._passing_evidence()
        first = validate_and_canonicalize(evidence, 1)
        second = validate_and_canonicalize(evidence, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["multiple_testing"]["corrected_p_value_ppm"], 10_000)
        self.assertEqual(first["pbo"]["pbo_ppm"], 0)
        with self.assertRaises(OverfittingValidationError):
            validate_and_canonicalize(replace(evidence, raw_p_value_ppm=0.5), 1)
        weakened_policy = replace(DEFAULT_POLICY, alpha_ppm=100_000)
        with self.assertRaises(OverfittingValidationError):
            validate_and_canonicalize(replace(evidence, policy=weakened_policy), 1)

    def test_assessment_is_idempotent_and_gates_all_candidate_or_higher_stages(self) -> None:
        trial, _, run = self._bound_trial("d-pass")
        before = self._count("overfitting_assessments")
        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=trial.trial_id,
                to_stage="CANDIDATE",
                evidence_artifact_id=run.artifact_id,
                recorded_at_ns=4,
            )
        self.assertEqual(self._count("overfitting_assessments"), before)

        first = self.registry.record_overfitting_assessment(
            trial_id=trial.trial_id,
            evidence_artifact_id=run.artifact_id,
            evidence=self._passing_evidence(),
            recorded_at_ns=5,
        )
        replay = self.registry.record_overfitting_assessment(
            trial_id=trial.trial_id,
            evidence_artifact_id=run.artifact_id,
            evidence=self._passing_evidence(),
            recorded_at_ns=5,
        )
        self.assertFalse(first.reused)
        self.assertTrue(replay.reused)
        self.assertEqual(first.assessment_id, replay.assessment_id)
        self.assertEqual(first.trial_count, 1)
        self.registry.verify_overfitting_assessments()

        candidate = self.registry.advance_trial_stage(
            trial_id=trial.trial_id,
            to_stage="CANDIDATE",
            evidence_artifact_id=run.artifact_id,
            recorded_at_ns=6,
        )
        promotable = self.registry.advance_trial_stage(
            trial_id=trial.trial_id,
            to_stage="PROMOTABLE",
            evidence_artifact_id=run.artifact_id,
            recorded_at_ns=7,
        )
        live = self.registry.advance_trial_stage(
            trial_id=trial.trial_id,
            to_stage="LIVE_CANDIDATE",
            evidence_artifact_id=run.artifact_id,
            recorded_at_ns=8,
        )
        self.assertEqual((candidate.stage, promotable.stage, live.stage), ("CANDIDATE", "PROMOTABLE", "LIVE_CANDIDATE"))

    def test_rejected_evidence_leaves_no_partial_assessment(self) -> None:
        trial, _, run = self._bound_trial("d-reject")
        valid = self._passing_evidence()
        bad_cases = (
            replace(valid, raw_p_value_ppm=60_000),
            replace(valid, cscv_partitions=(CscvPartition((12, 8), (8, 12)), CscvPartition((12, 8), (8, 12)))),
            replace(valid, regime_scores=(RegimeScore("BULL", 8), RegimeScore("RANGE", 7), RegimeScore("BEAR", -1))),
            replace(valid, neighbor_oos_scores_bps=(-1, 8)),
            replace(valid, stressed_cost_bps=9),
            replace(valid, walk_forward_folds=valid.walk_forward_folds[:2]),
            replace(valid, walk_forward_folds=(replace(valid.walk_forward_folds[0], purge_events=1),) + valid.walk_forward_folds[1:]),
            replace(valid, walk_forward_folds=(replace(valid.walk_forward_folds[0], embargo_events=1),) + valid.walk_forward_folds[1:]),
            replace(valid, walk_forward_folds=(replace(valid.walk_forward_folds[0], validation_start_event=9),) + valid.walk_forward_folds[1:]),
            replace(
                valid,
                walk_forward_folds=(
                    valid.walk_forward_folds[0],
                    WalkForwardFold(10, 18, 20, 27, 29, 39, 2, 2, 12, 10),
                    valid.walk_forward_folds[2],
                ),
            ),
        )
        for offset, bad in enumerate(bad_cases):
            with self.subTest(offset=offset):
                before = self._count("overfitting_assessments")
                with self.assertRaises(RegistryConflict):
                    self.registry.record_overfitting_assessment(
                        trial_id=trial.trial_id,
                        evidence_artifact_id=run.artifact_id,
                        evidence=bad,
                        recorded_at_ns=10 + offset,
                    )
                self.assertEqual(self._count("overfitting_assessments"), before)
        with self.assertRaises(OverfittingValidationError):
            validate_and_canonicalize(valid, 6)

    def test_holdout_and_stale_trial_count_block_new_promotion(self) -> None:
        trial, snapshot, run = self._bound_trial("d-holdout")
        holdout = self.registry.record_holdout_access(
            trial_id=trial.trial_id,
            evidence_artifact_id=snapshot.artifact_id,
            accessed_at_ns=4,
        )
        self.assertFalse(holdout.reused)
        with self.assertRaises(RegistryConflict):
            self.registry.record_overfitting_assessment(
                trial_id=trial.trial_id,
                evidence_artifact_id=run.artifact_id,
                evidence=self._passing_evidence(),
                recorded_at_ns=5,
            )
        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=trial.trial_id,
                to_stage="CANDIDATE",
                evidence_artifact_id=run.artifact_id,
                recorded_at_ns=6,
            )

        first, _, first_run = self._bound_trial("d-stale-a", family="family-d-stale", dataset_label="dataset-d-stale")
        self.registry.record_overfitting_assessment(
            trial_id=first.trial_id,
            evidence_artifact_id=first_run.artifact_id,
            evidence=self._passing_evidence(),
            recorded_at_ns=7,
        )
        self._bound_trial(
            "d-stale-b",
            family="family-d-stale",
            dataset_label="dataset-d-stale",
            code_label="d-stale-second-code",
            config_label="d-stale-second-config",
            identity_created_at_ns=8,
        )
        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=first.trial_id,
                to_stage="CANDIDATE",
                evidence_artifact_id=first_run.artifact_id,
                recorded_at_ns=8,
            )
        historical_replay = self.registry.record_overfitting_assessment(
            trial_id=first.trial_id,
            evidence_artifact_id=first_run.artifact_id,
            evidence=self._passing_evidence(),
            recorded_at_ns=7,
        )
        self.assertTrue(historical_replay.reused)
        connection = sqlite3.connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO trial_stage_transitions (
                        stage_transition_id, trial_id, from_stage, to_stage,
                        evidence_artifact_id, recorded_at_ns
                    ) VALUES (?, ?, 'EXPLORATORY', 'CANDIDATE', ?, 9)
                    """,
                    (digest("raw-stale-d-stage"), first.trial_id, first_run.artifact_id),
                )
        finally:
            connection.close()

    def test_raw_mutation_and_candidate_bypass_are_rejected(self) -> None:
        trial, _, run = self._bound_trial("d-raw")
        unassessed, _, unassessed_run = self._bound_trial(
            "d-raw-unassessed",
            family="family-d-raw-unassessed",
            dataset_label="dataset-d-raw-unassessed",
        )
        assessment = self.registry.record_overfitting_assessment(
            trial_id=trial.trial_id,
            evidence_artifact_id=run.artifact_id,
            evidence=self._passing_evidence(),
            recorded_at_ns=4,
        )
        connection = sqlite3.connect(self.database)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE overfitting_assessments SET trial_count = 99 WHERE assessment_id = ?",
                    (assessment.assessment_id,),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "DELETE FROM overfitting_assessments WHERE assessment_id = ?",
                    (assessment.assessment_id,),
                )
            with self.assertRaises(sqlite3.Error):
                connection.execute(
                    "INSERT OR REPLACE INTO overfitting_assessments SELECT * FROM overfitting_assessments",
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO trial_stage_transitions (
                        stage_transition_id, trial_id, from_stage, to_stage,
                        evidence_artifact_id, recorded_at_ns
                    ) VALUES (?, ?, 'EXPLORATORY', 'CANDIDATE', ?, 5)
                    """,
                    (digest("raw-d-stage"), trial.trial_id, digest("unbound-run")),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """
                    INSERT INTO trial_stage_transitions (
                        stage_transition_id, trial_id, from_stage, to_stage,
                        evidence_artifact_id, recorded_at_ns
                    ) VALUES (?, ?, 'EXPLORATORY', 'CANDIDATE', ?, 6)
                    """,
                    (
                        digest("raw-unassessed-d-stage"),
                        unassessed.trial_id,
                        unassessed_run.artifact_id,
                    ),
                )
        finally:
            connection.close()

    def test_forged_bound_assessment_cannot_unlock_a_public_promotion(self) -> None:
        trial, _, run = self._bound_trial("d-forged")
        forged_json = "{}"
        connection = self.registry._connect()
        try:
            connection.execute(
                """
                INSERT INTO overfitting_assessments (
                    assessment_id, trial_id, evidence_artifact_id, trial_count,
                    policy_sha256, canonical_evidence_json, evidence_sha256,
                    recorded_at_ns, passed
                ) VALUES (?, ?, ?, 1, ?, ?, ?, 4, 1)
                """,
                (
                    digest("forged-d-assessment"),
                    trial.trial_id,
                    run.artifact_id,
                    digest("forged-d-policy"),
                    forged_json,
                    sha256_bytes(forged_json.encode("ascii")),
                ),
            )
        finally:
            connection.close()
        before = self._count("trial_stage_transitions")
        with self.assertRaises(RegistryConflict):
            self.registry.verify_overfitting_assessments()
        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=trial.trial_id,
                to_stage="CANDIDATE",
                evidence_artifact_id=run.artifact_id,
                recorded_at_ns=5,
            )
        self.assertEqual(self._count("trial_stage_transitions"), before)

    def test_forged_trial_count_cannot_unlock_a_public_promotion(self) -> None:
        trial, _, run = self._bound_trial("d-forged-count")
        canonical = validate_and_canonicalize(self._passing_evidence(), 2)
        canonical_json = canonical_bytes(canonical).decode("ascii")
        connection = self.registry._connect()
        try:
            connection.execute(
                """
                INSERT INTO overfitting_assessments (
                    assessment_id, trial_id, evidence_artifact_id, trial_count,
                    policy_sha256, canonical_evidence_json, evidence_sha256,
                    recorded_at_ns, passed
                ) VALUES (?, ?, ?, 2, ?, ?, ?, 4, 1)
                """,
                (
                    digest("forged-d-count-assessment"),
                    trial.trial_id,
                    run.artifact_id,
                    canonical["policy_sha256"],
                    canonical_json,
                    sha256_bytes(canonical_json.encode("ascii")),
                ),
            )
        finally:
            connection.close()
        with self.assertRaises(RegistryConflict):
            self.registry.advance_trial_stage(
                trial_id=trial.trial_id,
                to_stage="CANDIDATE",
                evidence_artifact_id=run.artifact_id,
                recorded_at_ns=5,
            )

    def test_exploratory_runner_does_not_import_or_execute_heavy_gate(self) -> None:
        registry_source = inspect.getsource(ExperimentRegistry)
        self.assertNotIn("from .overfitting import", registry_source.split("def record_overfitting_assessment", 1)[0])
        self.assertNotIn("_validate_persisted_d(connection)", inspect.getsource(ExperimentRegistry.initialize))
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ENGINE_ROOT)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        fresh = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import research_engine.runner; "
                "raise SystemExit(int('research_engine.overfitting' in sys.modules))",
            ],
            check=False,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        module_tree = ast.parse((ENGINE_ROOT / "research_engine" / "overfitting.py").read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(node.value, float) for node in ast.walk(module_tree) if isinstance(node, ast.Constant)))


if __name__ == "__main__":
    unittest.main()
