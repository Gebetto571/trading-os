"""Forward-only A1/H0 compatibility tests for persisted A0 lineage databases."""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

from research_engine import registry as registry_module
from research_engine.errors import RegistryConflict
from research_engine.hashing import canonical_bytes, sha256_bytes, sha256_file
from research_engine.registry import ExperimentRegistry, LineageArtifact


MIGRATIONS = ENGINE_ROOT / "migrations"
SOURCE_RUNTIME = ENGINE_ROOT / "runtime" / "experiments.sqlite3"
MARKER = ".research-engine-disposable-lineage-fixture"
MARKER_CONTENT = "research-engine-disposable-lineage-fixture-v1\n"


def digest(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def _rows(connection: sqlite3.Connection, statement: str) -> tuple[tuple[object, ...], ...]:
    return tuple(tuple(row) for row in connection.execute(statement))


def _metadata_snapshot(database: Path) -> dict[str, object]:
    connection = sqlite3.connect(database)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        snapshot: dict[str, object] = {
            "ledger": _rows(
                connection,
                "SELECT migration_name, migration_sha256, applied_at_ns "
                "FROM schema_migrations ORDER BY migration_name",
            ),
            "objects": _rows(
                connection,
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE type IN ('table', 'index', 'trigger') "
                "AND name NOT LIKE 'sqlite_%' ORDER BY type, name",
            ),
            "registry": _rows(
                connection,
                "SELECT experiment_id, trial_id, strategy_family_id, dataset_path, "
                "dataset_identity, dataset_sha256, code_sha256, config_sha256, "
                "started_at_ns, finished_at_ns, status, result_artifact_id, canonical_summary_json "
                "FROM experiment_registry ORDER BY experiment_id",
            ),
            "artifacts": _rows(
                connection,
                "SELECT artifact_id, artifact_type, identity_sha256, content_sha256, "
                "canonical_payload_json, created_at_ns FROM artifacts ORDER BY artifact_id",
            ),
            "relations": _rows(
                connection,
                "SELECT parent_artifact_id, child_artifact_id, relation_type, created_at_ns "
                "FROM relations ORDER BY parent_artifact_id, child_artifact_id, relation_type",
            ),
            "trials": _rows(
                connection,
                "SELECT trial_id, strategy_family_id, identity_sha256, created_at_ns "
                "FROM trials ORDER BY trial_id",
            ),
            "experiments": _rows(
                connection,
                "SELECT experiment_id, trial_id, data_snapshot_artifact_id, "
                "experiment_run_artifact_id, code_sha256, config_sha256, result_artifact_id, "
                "created_at_ns FROM experiments ORDER BY experiment_id",
            ),
            "promotions": _rows(
                connection,
                "SELECT promotion_id, source_artifact_id, target_artifact_id, "
                "decision_artifact_id, promotion_sha256, created_at_ns FROM promotions "
                "ORDER BY promotion_id",
            ),
        }
        if "trial_identities" in tables:
            snapshot["trial_identities"] = _rows(
                connection,
                "SELECT trial_id, strategy_family_id, data_snapshot_artifact_id, "
                "dataset_sha256, code_sha256, config_sha256, identity_sha256, created_at_ns "
                "FROM trial_identities ORDER BY trial_id",
            )
            snapshot["holdout_accesses"] = _rows(
                connection,
                "SELECT holdout_access_id, trial_id, evidence_artifact_id, accessed_at_ns "
                "FROM holdout_accesses ORDER BY holdout_access_id",
            )
            snapshot["trial_stage_transitions"] = _rows(
                connection,
                "SELECT stage_transition_id, trial_id, from_stage, to_stage, "
                "evidence_artifact_id, recorded_at_ns FROM trial_stage_transitions "
                "ORDER BY stage_transition_id",
            )
            snapshot["overfitting_assessments"] = _rows(
                connection,
                "SELECT assessment_id, trial_id, evidence_artifact_id, trial_count, "
                "policy_sha256, canonical_evidence_json, evidence_sha256, recorded_at_ns, passed "
                "FROM overfitting_assessments ORDER BY assessment_id",
            ) if "overfitting_assessments" in tables else ()
        else:
            snapshot["trial_identities"] = ()
            snapshot["holdout_accesses"] = ()
            snapshot["trial_stage_transitions"] = ()
            snapshot["overfitting_assessments"] = ()
        if "h1_raw_lineage_evidence" in tables:
            snapshot["h1_raw_lineage_evidence"] = _rows(
                connection,
                "SELECT opaque_evidence_sha256, raw_bytes, c3_task_uuid, c3_result_uuid, "
                "c3_result_raw_sha256, c3_exporter_commit, c2_canonical_wire_sha256, "
                "c2_materialization_id, created_at_ns "
                "FROM h1_raw_lineage_evidence ORDER BY opaque_evidence_sha256",
            )
            snapshot["h1_lineage_materializations"] = _rows(
                connection,
                "SELECT lineage_id, opaque_evidence_sha256, data_snapshot_artifact_id, "
                "experiment_run_artifact_id, strategy_candidate_artifact_id, "
                "strategy_package_artifact_id, replay_artifact_id, paper_artifact_id, "
                "decision_artifact_id, c0_data_snapshot_id, c0_experiment_run_id, "
                "c0_candidate_id, c0_package_id, c0_trace_id, c0_strategy_family_id, "
                "c0_code_sha256, c0_config_sha256, created_at_ns "
                "FROM h1_lineage_materializations ORDER BY lineage_id",
            )
        else:
            snapshot["h1_raw_lineage_evidence"] = ()
            snapshot["h1_lineage_materializations"] = ()
        return snapshot
    finally:
        connection.close()


class MigrationCompatibilityTests(unittest.TestCase):
    def _registry(self, database: Path, migrations: Path = MIGRATIONS) -> ExperimentRegistry:
        return ExperimentRegistry(database, migrations)

    def _make_f36_fixture(self, database: Path) -> dict[str, object]:
        """Create a temporary, exact-shape f36 specimen with one linked A0 lineage."""
        experiment_id = digest("f36-experiment")
        trial_id = "f36-trial"
        strategy_family_id = "deterministic-event-study-v1"
        dataset_path = "/readonly/f36-candles.parquet"
        dataset_identity = digest("f36-dataset-identity")
        dataset_sha256 = digest("f36-dataset-content")
        code_sha256 = digest("f36-code")
        config_sha256 = digest("f36-config")
        canonical_summary = {"legacy": "f36"}
        result_artifact_id = sha256_bytes(canonical_bytes(canonical_summary))
        snapshot = LineageArtifact(
            artifact_type="DataSnapshot",
            identity_sha256=dataset_identity,
            content_sha256=dataset_sha256,
            payload={
                "dataset_identity": dataset_identity,
                "dataset_path": dataset_path,
                "dataset_sha256": dataset_sha256,
            },
        )
        experiment_run = LineageArtifact(
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
                "trial_id": trial_id,
            },
        )

        connection = sqlite3.connect(database)
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            ExperimentRegistry._ensure_migration_ledger(connection)
            for migration_name in (
                registry_module._REGISTRY_MIGRATION,
                registry_module._LINEAGE_MIGRATION,
            ):
                migration_path = MIGRATIONS / migration_name
                ExperimentRegistry._execute_sql_script(
                    connection,
                    migration_path.read_text(encoding="utf-8"),
                )
                marker_digest = (
                    registry_module._LEGACY_F36_LINEAGE_SHA256
                    if migration_name == registry_module._LINEAGE_MIGRATION
                    else sha256_bytes(migration_path.read_bytes())
                )
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?, ?)",
                    (migration_name, marker_digest, 1),
                )
            for trigger_name in registry_module._COMPATIBILITY_HARDENING_TRIGGERS:
                connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
            connection.executescript(registry_module._LEGACY_F36_RELATION_TRIGGER_SQL)
            connection.execute(
                """
                INSERT INTO experiment_registry (
                    experiment_id, trial_id, strategy_family_id, dataset_path,
                    dataset_identity, dataset_sha256, code_sha256, config_sha256,
                    started_at_ns, finished_at_ns, status, result_artifact_id,
                    canonical_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 2, 'completed', ?, ?)
                """,
                (
                    experiment_id,
                    trial_id,
                    strategy_family_id,
                    dataset_path,
                    dataset_identity,
                    dataset_sha256,
                    code_sha256,
                    config_sha256,
                    result_artifact_id,
                    canonical_bytes(canonical_summary).decode("ascii"),
                ),
            )
            for item in (snapshot, experiment_run):
                connection.execute(
                    """
                    INSERT INTO artifacts (
                        artifact_id, artifact_type, identity_sha256, content_sha256,
                        canonical_payload_json, created_at_ns
                    ) VALUES (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        item.artifact_id,
                        item.artifact_type,
                        item.identity_sha256,
                        item.content_sha256,
                        item.canonical_payload_json,
                    ),
                )
            connection.execute(
                "INSERT INTO relations VALUES (?, ?, 'derives_from', 1)",
                (snapshot.artifact_id, experiment_run.artifact_id),
            )
            connection.execute(
                "INSERT INTO trials VALUES (?, ?, ?, 1)",
                (
                    trial_id,
                    strategy_family_id,
                    sha256_bytes(
                        canonical_bytes(
                            {"strategy_family_id": strategy_family_id, "trial_id": trial_id}
                        )
                    ),
                ),
            )
            connection.execute(
                """
                INSERT INTO experiments (
                    experiment_id, trial_id, data_snapshot_artifact_id,
                    experiment_run_artifact_id, code_sha256, config_sha256,
                    result_artifact_id, created_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    experiment_id,
                    trial_id,
                    snapshot.artifact_id,
                    experiment_run.artifact_id,
                    code_sha256,
                    config_sha256,
                    result_artifact_id,
                ),
            )
            connection.commit()
        finally:
            connection.close()

        return {
            "experiment_id": experiment_id,
            "trial_id": trial_id,
            "strategy_family_id": strategy_family_id,
            "dataset_path": dataset_path,
            "dataset_identity": dataset_identity,
            "dataset_sha256": dataset_sha256,
            "code_sha256": code_sha256,
            "config_sha256": config_sha256,
            "canonical_summary": canonical_summary,
            "result_artifact_id": result_artifact_id,
            "snapshot": snapshot,
            "experiment_run": experiment_run,
        }

    def _assert_f36_shape(self, database: Path) -> None:
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(
                ExperimentRegistry._schema_fingerprints(connection),
                (
                    registry_module._EXPECTED_BASE_SCHEMA_FINGERPRINT,
                    registry_module._EXPECTED_F36_TRIGGER_FINGERPRINT,
                ),
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertIsNone(connection.execute("PRAGMA foreign_key_check").fetchone())
        finally:
            connection.close()

    def _assert_final_shape(self, database: Path) -> None:
        connection = sqlite3.connect(database)
        try:
            self.assertEqual(
                ExperimentRegistry._schema_fingerprints(connection),
                (
                    registry_module._EXPECTED_H1_BASE_SCHEMA_FINGERPRINT,
                    registry_module._EXPECTED_H1_TRIGGER_FINGERPRINT,
                ),
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertIsNone(connection.execute("PRAGMA foreign_key_check").fetchone())
        finally:
            connection.close()

    def test_blank_database_applies_current_migrations_and_second_initialize_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "blank.sqlite3"
            registry = self._registry(database)
            registry.initialize()
            first = _metadata_snapshot(database)
            registry.initialize()
            self.assertEqual(_metadata_snapshot(database), first)
            self._assert_final_shape(database)
            self.assertEqual(
                tuple(item[0] for item in first["ledger"]),
                (
                    registry_module._REGISTRY_MIGRATION,
                    registry_module._LINEAGE_MIGRATION,
                    registry_module._COMPATIBILITY_MIGRATION,
                    registry_module._D0_MIGRATION,
                    registry_module._D_MIGRATION,
                    registry_module._H1_MIGRATION,
                ),
            )

    def test_known_f36_fixture_upgrades_without_rewriting_legacy_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy.sqlite3"
            self._make_f36_fixture(database)
            self._assert_f36_shape(database)
            before = _metadata_snapshot(database)

            registry = self._registry(database)
            registry.initialize()
            after = _metadata_snapshot(database)
            self._assert_final_shape(database)
            self.assertEqual(after["registry"], before["registry"])
            self.assertEqual(after["artifacts"], before["artifacts"])
            self.assertEqual(after["relations"], before["relations"])
            self.assertEqual(after["trials"], before["trials"])
            self.assertEqual(after["experiments"], before["experiments"])
            self.assertEqual(after["promotions"], before["promotions"])
            self.assertEqual(after["trial_identities"], ())
            self.assertEqual(after["holdout_accesses"], ())
            self.assertEqual(after["trial_stage_transitions"], ())
            self.assertEqual(after["overfitting_assessments"], ())
            self.assertEqual(after["h1_raw_lineage_evidence"], ())
            self.assertEqual(after["h1_lineage_materializations"], ())
            self.assertEqual(after["ledger"][:2], before["ledger"])
            self.assertEqual(after["ledger"][-4][0], registry_module._COMPATIBILITY_MIGRATION)
            self.assertEqual(after["ledger"][-3][0], registry_module._D0_MIGRATION)
            self.assertEqual(after["ledger"][-2][0], registry_module._D_MIGRATION)
            self.assertEqual(after["ledger"][-1][0], registry_module._H1_MIGRATION)

            registry.initialize()
            self.assertEqual(_metadata_snapshot(database), after)

    def test_runtime_source_byte_copy_upgrades_without_mutating_source(self) -> None:
        if not SOURCE_RUNTIME.is_file() or SOURCE_RUNTIME.is_symlink():
            self.skipTest("the ignored A0 source runtime specimen is unavailable")
        sidecars = (
            SOURCE_RUNTIME.with_name(SOURCE_RUNTIME.name + "-wal"),
            SOURCE_RUNTIME.with_name(SOURCE_RUNTIME.name + "-shm"),
        )
        self.assertFalse(any(path.exists() for path in sidecars), "source runtime has SQLite sidecars")
        source_before = sha256_file(SOURCE_RUNTIME)

        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "a0-byte-copy.sqlite3"
            shutil.copyfile(SOURCE_RUNTIME, copied)
            self.assertEqual(sha256_file(copied), source_before)
            self._registry(copied).initialize()
            self._assert_final_shape(copied)
            connection = sqlite3.connect(copied)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT migration_sha256 FROM schema_migrations "
                        "WHERE migration_name = ?",
                        (registry_module._LINEAGE_MIGRATION,),
                    ).fetchone()[0],
                    registry_module._LEGACY_F36_LINEAGE_SHA256,
                )
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
                        (registry_module._COMPATIBILITY_MIGRATION,),
                    ).fetchone(),
                )
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
                        (registry_module._D0_MIGRATION,),
                    ).fetchone(),
                )
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
                        (registry_module._D_MIGRATION,),
                    ).fetchone(),
                )
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
                        (registry_module._H1_MIGRATION,),
                    ).fetchone(),
                )
            finally:
                connection.close()
        self.assertEqual(sha256_file(SOURCE_RUNTIME), source_before)

    def test_legacy_snapshot_replay_and_relocation_reuse_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy.sqlite3"
            values = self._make_f36_fixture(database)
            registry = self._registry(database)
            registry.initialize()

            replay = registry.record_or_reuse(
                experiment_id=values["experiment_id"],
                trial_id=values["trial_id"],
                strategy_family_id=values["strategy_family_id"],
                dataset_path=values["dataset_path"],
                dataset_identity=values["dataset_identity"],
                dataset_sha256=values["dataset_sha256"],
                code_sha256=values["code_sha256"],
                config_sha256=values["config_sha256"],
                started_at_ns=1,
                finished_at_ns=2,
                result_artifact_id=values["result_artifact_id"],
                canonical_summary=values["canonical_summary"],
            )
            self.assertTrue(replay.reused)

            relocation_summary = {"legacy": "relocated"}
            registry.record_or_reuse(
                experiment_id=digest("f36-relocated-experiment"),
                trial_id=values["trial_id"],
                strategy_family_id=values["strategy_family_id"],
                dataset_path="/readonly/moved-f36-candles.parquet",
                dataset_identity=values["dataset_identity"],
                dataset_sha256=values["dataset_sha256"],
                code_sha256=values["code_sha256"],
                config_sha256=digest("f36-relocated-config"),
                started_at_ns=3,
                finished_at_ns=4,
                result_artifact_id=sha256_bytes(canonical_bytes(relocation_summary)),
                canonical_summary=relocation_summary,
            )
            connection = sqlite3.connect(database)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM artifacts WHERE artifact_type = 'DataSnapshot'"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT canonical_payload_json FROM artifacts WHERE artifact_id = ?",
                        (values["snapshot"].artifact_id,),
                    ).fetchone()[0],
                    values["snapshot"].canonical_payload_json,
                )
            finally:
                connection.close()

            before = _metadata_snapshot(database)
            mismatch_summary = {"legacy": "mismatched-content"}
            with self.assertRaises(RegistryConflict):
                registry.record_or_reuse(
                    experiment_id=digest("f36-content-mismatch"),
                    trial_id=values["trial_id"],
                    strategy_family_id=values["strategy_family_id"],
                    dataset_path="/readonly/mismatched-f36-candles.parquet",
                    dataset_identity=values["dataset_identity"],
                    dataset_sha256=digest("f36-altered-content"),
                    code_sha256=values["code_sha256"],
                    config_sha256=digest("f36-content-mismatch-config"),
                    started_at_ns=5,
                    finished_at_ns=6,
                    result_artifact_id=sha256_bytes(canonical_bytes(mismatch_summary)),
                    canonical_summary=mismatch_summary,
                )
            self.assertEqual(_metadata_snapshot(database), before)

    def test_unknown_or_wrong_legacy_schema_fails_closed_without_delta(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty_ledger_database = root / "empty-ledger.sqlite3"
            connection = sqlite3.connect(empty_ledger_database)
            try:
                connection.execute(
                    """
                    CREATE TABLE schema_migrations (
                        migration_name TEXT PRIMARY KEY,
                        migration_sha256 TEXT NOT NULL,
                        applied_at_ns INTEGER NOT NULL
                    )
                    """
                )
                connection.execute("CREATE TABLE forged_unversioned_record (value TEXT NOT NULL)")
                connection.execute("INSERT INTO forged_unversioned_record VALUES ('must-remain')")
                connection.commit()
            finally:
                connection.close()
            empty_ledger_before = sha256_file(empty_ledger_database)
            with self.assertRaises(RegistryConflict):
                self._registry(empty_ledger_database).initialize()
            self.assertEqual(sha256_file(empty_ledger_database), empty_ledger_before)

            incomplete_d0_database = root / "incomplete-d0.sqlite3"
            incomplete_registry = self._registry(incomplete_d0_database)
            incomplete_registry.initialize()
            snapshot = LineageArtifact(
                artifact_type="DataSnapshot",
                identity_sha256=digest("incomplete-d0-snapshot"),
                content_sha256=digest("incomplete-d0-content"),
                payload={"contract_label": "incomplete-d0-snapshot"},
            )
            run = LineageArtifact(
                artifact_type="ExperimentRun",
                identity_sha256=digest("incomplete-d0-run"),
                content_sha256=digest("incomplete-d0-result"),
                payload={"contract_label": "incomplete-d0-run"},
            )
            incomplete_registry.record_contract_bundle(
                (snapshot, run),
                ((snapshot.artifact_id, run.artifact_id),),
            )
            strategy_family_id = "incomplete-d0-family"
            code_sha256 = digest("incomplete-d0-code")
            config_sha256 = digest("incomplete-d0-config")
            trial_id = sha256_bytes(
                canonical_bytes(
                    {
                        "code_sha256": code_sha256,
                        "config_sha256": config_sha256,
                        "data_snapshot_artifact_id": snapshot.artifact_id,
                        "dataset_sha256": snapshot.content_sha256,
                        "strategy_family_id": strategy_family_id,
                    }
                )
            )
            connection = sqlite3.connect(incomplete_d0_database)
            try:
                connection.execute(
                    "INSERT INTO trials VALUES (?, ?, ?, 1)",
                    (
                        trial_id,
                        strategy_family_id,
                        sha256_bytes(
                            canonical_bytes(
                                {"strategy_family_id": strategy_family_id, "trial_id": trial_id}
                            )
                        ),
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO trial_identities (
                        trial_id, strategy_family_id, data_snapshot_artifact_id,
                        dataset_sha256, code_sha256, config_sha256, identity_sha256,
                        created_at_ns
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        trial_id,
                        strategy_family_id,
                        snapshot.artifact_id,
                        snapshot.content_sha256,
                        code_sha256,
                        config_sha256,
                        trial_id,
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            incomplete_before = _metadata_snapshot(incomplete_d0_database)
            with self.assertRaises(RegistryConflict):
                incomplete_registry.initialize()
            self.assertEqual(_metadata_snapshot(incomplete_d0_database), incomplete_before)

            unknown_database = root / "unknown.sqlite3"
            self._make_f36_fixture(unknown_database)
            connection = sqlite3.connect(unknown_database)
            try:
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?, ?)",
                    ("007_future.sql", digest("future-migration"), 9),
                )
                connection.commit()
            finally:
                connection.close()
            before_unknown = _metadata_snapshot(unknown_database)
            with self.assertRaises(RegistryConflict):
                self._registry(unknown_database).initialize()
            self.assertEqual(_metadata_snapshot(unknown_database), before_unknown)

            wrong_schema_database = root / "wrong-schema.sqlite3"
            self._make_f36_fixture(wrong_schema_database)
            connection = sqlite3.connect(wrong_schema_database)
            try:
                connection.execute("DROP TRIGGER relations_no_delete")
                connection.commit()
            finally:
                connection.close()
            before_wrong_schema = _metadata_snapshot(wrong_schema_database)
            with self.assertRaises(RegistryConflict):
                self._registry(wrong_schema_database).initialize()
            self.assertEqual(_metadata_snapshot(wrong_schema_database), before_wrong_schema)

    def test_legacy_hash_mismatch_and_injected_failure_roll_back_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            malformed_database = root / "malformed.sqlite3"
            self._make_f36_fixture(malformed_database)
            connection = sqlite3.connect(malformed_database)
            try:
                connection.execute(
                    "UPDATE experiment_registry SET result_artifact_id = ?",
                    (digest("tampered-result"),),
                )
                connection.commit()
            finally:
                connection.close()
            malformed_before = _metadata_snapshot(malformed_database)
            with self.assertRaises(RegistryConflict):
                self._registry(malformed_database).initialize()
            self.assertEqual(_metadata_snapshot(malformed_database), malformed_before)

            failing_database = root / "failing.sqlite3"
            self._make_f36_fixture(failing_database)
            copied_migrations = root / "migrations"
            shutil.copytree(MIGRATIONS, copied_migrations)
            (copied_migrations / "006_injected_failure.sql").write_text(
                "CREATE TABLE injected_failure_probe (id INTEGER);\nSELECT unknown_function();\n",
                encoding="utf-8",
            )
            failing_before = _metadata_snapshot(failing_database)
            with self.assertRaises(RegistryConflict):
                self._registry(failing_database, copied_migrations).initialize()
            self.assertEqual(_metadata_snapshot(failing_database), failing_before)

    def test_d0_rejects_temporary_pre_d0_rollback_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "legacy.sqlite3"
            self._make_f36_fixture(database)
            registry = self._registry(database)
            registry.initialize()
            upgraded = _metadata_snapshot(database)
            (root / MARKER).write_text(MARKER_CONTENT, encoding="utf-8")

            with self.assertRaises(RegistryConflict):
                registry.rollback_compatibility_for_disposable_fixture()
            with self.assertRaises(RegistryConflict):
                registry.rollback_lineage_for_disposable_fixture()
            self.assertEqual(_metadata_snapshot(database), upgraded)
            self._assert_final_shape(database)

    def test_upgraded_legacy_copy_enforces_raw_fk_and_immutability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy.sqlite3"
            values = self._make_f36_fixture(database)
            self._registry(database).initialize()
            before = _metadata_snapshot(database)

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 0)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT INTO relations (parent_artifact_id, child_artifact_id, relation_type, created_at_ns)
                        VALUES (?, ?, 'derives_from', 7)
                        """,
                        (digest("missing-parent"), digest("missing-child")),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        "UPDATE artifacts SET content_sha256 = ? WHERE artifact_id = ?",
                        (digest("tampered-content"), values["snapshot"].artifact_id),
                    )
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute(
                        """
                        INSERT OR REPLACE INTO artifacts (
                            artifact_id, artifact_type, identity_sha256, content_sha256,
                            canonical_payload_json, created_at_ns
                        ) VALUES (?, 'DataSnapshot', ?, ?, '{}', 8)
                        """,
                        (
                            values["snapshot"].artifact_id,
                            values["dataset_identity"],
                            values["dataset_sha256"],
                        ),
                    )
            finally:
                connection.close()
            self.assertEqual(_metadata_snapshot(database), before)


if __name__ == "__main__":
    unittest.main()
