"""Single-writer, immutable SQLite lineage registry for local research evidence."""

from __future__ import annotations

import json
import re
import sqlite3
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

from .errors import RegistryBusy, RegistryConflict, RuntimeBoundaryError
from .hashing import canonical_bytes, sha256_bytes

if TYPE_CHECKING:
    from .overfitting import OverfittingEvidence


_ARTIFACT_TYPES = frozenset(
    {
        "DataSnapshot",
        "ExperimentRun",
        "StrategyCandidate",
        "StrategyPackage",
        "Replay",
        "Paper",
        "Decision",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_DISPOSABLE_MARKER = ".research-engine-disposable-lineage-fixture"
_DISPOSABLE_MARKER_CONTENT = "research-engine-disposable-lineage-fixture-v1\n"
_REGISTRY_MIGRATION = "001_experiment_registry.sql"
_LINEAGE_MIGRATION = "002_lineage_foundation.sql"
_COMPATIBILITY_MIGRATION = "003_lineage_compatibility_hardening.sql"
_D0_MIGRATION = "004_trial_identity_holdout_gate.sql"
_D_MIGRATION = "005_overfitting_safety_gate.sql"
_H1_MIGRATION = "006_h1_raw_lineage_evidence.sql"
_TRIAL_STAGES = (
    "EXPLORATORY",
    "CANDIDATE",
    "PROMOTABLE",
    "LIVE_CANDIDATE",
)
_TRIAL_STAGE_PREDECESSOR = {
    "CANDIDATE": "EXPLORATORY",
    "PROMOTABLE": "CANDIDATE",
    "LIVE_CANDIDATE": "PROMOTABLE",
}

# This is the only legacy 002 marker admitted by the A1/H0 compatibility path.
# It is the byte-level marker held by the persisted A0 runtime, not a general
# migration-checksum allowlist.
_LEGACY_F36_LINEAGE_SHA256 = "f36dcfa089b599ad41fc7339eb75baea5437e1ed300382da322c4c37eaeda00f"
_CURRENT_LINEAGE_SHA256 = "ce0395f281908425efd46fb40fbfb410fb216a4d5a887623b2d7ecc2e900f050"

# sqlite_master fingerprints use canonical JSON of non-internal table/index and
# trigger definitions with whitespace collapsed. They pin the accepted legacy
# shape before any forward migration is allowed to write.
_EXPECTED_BASE_SCHEMA_FINGERPRINT = "d7889df9e1ed47e81fcdd18b23e1efab2e4e310efa02f0122f80230448654027"
_EXPECTED_F36_TRIGGER_FINGERPRINT = "f442e3cc08d9baede5917ef5ac4f8ddf8ae66752e21d222c54b31cfe16eb118b"
_EXPECTED_FINAL_TRIGGER_FINGERPRINT = "10f4a9f33e819b7e416a58fe5f5ec71747b190529a2c409ae01246373ca2b629"
_EXPECTED_A0_BASE_SCHEMA_FINGERPRINT = "8ef37f0c1c9fb652cc62c6630f06acaa59aa5051f82d9ae1e2a39fd631415774"
_EXPECTED_NO_TRIGGER_FINGERPRINT = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
# D0 fingerprints bind the exact add-only 004 schema before a registry accepts
# its marker. They cover tables/indexes and triggers independently.
_EXPECTED_D0_BASE_SCHEMA_FINGERPRINT = "829457983564825ae719a9c05cefccff8dad77e98e405c833bab858e7bf020a0"
_EXPECTED_D0_TRIGGER_FINGERPRINT = "2b3ba2c20a5260e075b5bdc76adb4bbe1b8bdb540629111d86e35659b552dff1"
# Bound after the add-only D migration is finalized.  These constants pin both
# the table/index shape and all immutable/raw-SQL gate triggers.
_EXPECTED_D_BASE_SCHEMA_FINGERPRINT = "af7dfe980f3e3939bb52188095a8205364b8585e5edc3da1fa9c28ab4b602488"
_EXPECTED_D_TRIGGER_FINGERPRINT = "d5a288dd39057136acfbc9a534a0a1fdd08e1a638b784bc34e977113ad15bf14"
# Bound after the additive H1 migration is finalized. These remain separate
# from the D fingerprints so an immutable 005-only database stays recognized.
_EXPECTED_H1_BASE_SCHEMA_FINGERPRINT = "4ea0033714527dae95cac7ce516da6783ee170466d1e0c26aecf83d8c7a620f2"
_EXPECTED_H1_TRIGGER_FINGERPRINT = "30dfea68ade071ed3d5b6c35a8be5f766b1d291fc5d34d74ac5e61e1d6a286d6"

_COMPATIBILITY_HARDENING_TRIGGERS = (
    "relations_require_adjacent_chain",
    "experiments_require_existing_contract",
    "promotions_require_existing_artifacts",
    "artifacts_no_replace",
    "relations_no_replace",
    "trials_no_replace",
    "experiments_no_replace",
    "promotions_no_replace",
    "experiment_registry_no_replace",
    "schema_migrations_no_replace",
    "schema_migrations_no_update",
    "schema_migrations_no_delete",
    "experiment_registry_no_update",
    "experiment_registry_no_delete",
)

_LEGACY_F36_RELATION_TRIGGER_SQL = """
CREATE TRIGGER relations_require_adjacent_chain
BEFORE INSERT ON relations
FOR EACH ROW
WHEN NOT (
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
BEGIN
    SELECT RAISE(ABORT, 'invalid directional lineage relation');
END;
"""

_SCHEMA_MIGRATIONS_NO_DELETE_TRIGGER_SQL = """
CREATE TRIGGER schema_migrations_no_delete
BEFORE DELETE ON schema_migrations
BEGIN
    SELECT RAISE(ABORT, 'migration marker deletion is forbidden');
END;
"""


@dataclass(frozen=True)
class RegistryRecord:
    """The durable result returned for either a new or replayed experiment."""

    canonical_summary: dict[str, Any]
    result_artifact_id: str
    reused: bool
    sqlite_write_elapsed_ns: int
    sqlite_read_elapsed_ns: int


@dataclass(frozen=True)
class LineageArtifact:
    """An immutable, content-addressed lineage artifact contract."""

    artifact_type: str
    identity_sha256: str
    content_sha256: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if self.artifact_type not in _ARTIFACT_TYPES:
            raise RegistryConflict(f"unsupported artifact type: {self.artifact_type}")
        _require_sha256(self.identity_sha256, "artifact identity_sha256")
        _require_sha256(self.content_sha256, "artifact content_sha256")
        if not isinstance(self.payload, dict):
            raise RegistryConflict("artifact payload must be an object")

    @property
    def canonical_payload_json(self) -> str:
        return canonical_bytes(self.payload).decode("ascii")

    @property
    def artifact_id(self) -> str:
        return sha256_bytes(
            canonical_bytes(
                {
                    "artifact_type": self.artifact_type,
                    "content_sha256": self.content_sha256,
                    "identity_sha256": self.identity_sha256,
                    "payload": self.payload,
                }
            )
        )


@dataclass(frozen=True)
class LineageBundleResult:
    """Outcome of a contract-only lineage bundle write or exact replay."""

    artifact_ids: tuple[str, ...]
    reused: bool
    sqlite_write_elapsed_ns: int
    sqlite_read_elapsed_ns: int


@dataclass(frozen=True)
class TrialIdentityResult:
    """Immutable D0 trial identity and its deterministic family/dataset count."""

    trial_id: str
    trial_count: int
    reused: bool
    sqlite_write_elapsed_ns: int
    sqlite_read_elapsed_ns: int


@dataclass(frozen=True)
class HoldoutAccessResult:
    """Append-only D0 holdout access outcome for an exact replay or new record."""

    holdout_access_id: str
    reused: bool
    sqlite_write_elapsed_ns: int
    sqlite_read_elapsed_ns: int


@dataclass(frozen=True)
class TrialStageResult:
    """Append-only D0 stage transition outcome for an exact replay or new record."""

    stage_transition_id: str
    trial_id: str
    stage: str
    reused: bool
    sqlite_write_elapsed_ns: int
    sqlite_read_elapsed_ns: int


@dataclass(frozen=True)
class OverfittingAssessmentResult:
    """Immutable D assessment write or exact replay outcome."""

    assessment_id: str
    trial_id: str
    evidence_artifact_id: str
    trial_count: int
    policy_sha256: str
    reused: bool
    sqlite_write_elapsed_ns: int
    sqlite_read_elapsed_ns: int


@dataclass(frozen=True)
class H1LineageResult:
    """Immutable H1 producer write or exact replay outcome."""

    lineage_id: str
    opaque_evidence_sha256: str
    artifact_ids: tuple[str, ...]
    reused: bool
    sqlite_write_elapsed_ns: int
    sqlite_read_elapsed_ns: int


@dataclass(frozen=True)
class H1LineageReadback:
    """Byte-preserving, queryable H1 lineage evidence."""

    lineage_id: str
    opaque_evidence_sha256: str
    opaque_bytes: bytes
    artifact_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ArtifactEnsureResult:
    """Resolved immutable artifact identity for an insert or exact replay."""

    artifact_id: str
    changed: bool


class ExperimentRegistry:
    """A local SQLite boundary with one writer, immutable lineage, and safe migrations."""

    def __init__(self, database_path: Path, migration_path: Path) -> None:
        self._database_path = database_path
        self._migration_dir = migration_path if migration_path.is_dir() else migration_path.parent

    def initialize(self) -> None:
        """Apply checksum-pinned migrations under one immediate write transaction."""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._validate_storage_paths()
        connection = self._connect()
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                raise RegistryBusy("registry initialization could not acquire the writer lock") from error

            migration_paths = self._migration_paths()
            migration_digests = {
                path.name: sha256_bytes(self._read_migration(path))
                for path in migration_paths
            }
            self._ensure_migration_ledger(connection)
            legacy_marker = self._preflight_migration_state(connection, migration_digests)

            for migration_path in migration_paths:
                name = migration_path.name
                raw = self._read_migration(migration_path)
                digest = migration_digests[name]
                existing = connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE migration_name = ?",
                    (name,),
                ).fetchone()
                if existing is not None:
                    legacy_002 = (
                        name == _LINEAGE_MIGRATION
                        and existing[0] == _LEGACY_F36_LINEAGE_SHA256
                        and legacy_marker == _LEGACY_F36_LINEAGE_SHA256
                    )
                    if existing[0] != digest and not legacy_002:
                        raise RegistryConflict(f"migration checksum changed after apply: {name}")
                    continue
                self._execute_sql_script(connection, raw.decode("utf-8"))
                connection.execute(
                    """
                    INSERT INTO schema_migrations (migration_name, migration_sha256, applied_at_ns)
                    VALUES (?, ?, ?)
                    """,
                    (name, digest, time.time_ns()),
                )
            self._preflight_migration_state(connection, migration_digests)
            connection.execute("COMMIT")
        except RegistryConflict:
            self._rollback(connection)
            raise
        except UnicodeDecodeError as error:
            self._rollback(connection)
            raise RegistryConflict("migration must be UTF-8 text") from error
        except sqlite3.Error as error:
            self._rollback(connection)
            raise RegistryConflict("registry migration failed closed") from error
        finally:
            connection.close()

    def record_or_reuse(
        self,
        *,
        experiment_id: str,
        trial_id: str,
        strategy_family_id: str,
        dataset_path: str,
        dataset_identity: str,
        dataset_sha256: str,
        code_sha256: str,
        config_sha256: str,
        started_at_ns: int,
        finished_at_ns: int,
        result_artifact_id: str,
        canonical_summary: dict[str, Any],
    ) -> RegistryRecord:
        """Commit one A0 result and its minimal lineage atomically, or replay it exactly."""
        _require_sha256(experiment_id, "experiment_id")
        _require_sha256(dataset_identity, "dataset_identity")
        _require_sha256(dataset_sha256, "dataset_sha256")
        _require_sha256(code_sha256, "code_sha256")
        _require_sha256(config_sha256, "config_sha256")
        _require_sha256(result_artifact_id, "result_artifact_id")
        _require_nonempty(trial_id, "trial_id")
        _require_nonempty(strategy_family_id, "strategy_family_id")
        _require_nonempty(dataset_path, "dataset_path")
        if not isinstance(started_at_ns, int) or not isinstance(finished_at_ns, int):
            raise RegistryConflict("experiment timestamps must be integers")

        serialized_summary = canonical_bytes(canonical_summary).decode("ascii")
        if result_artifact_id != sha256_bytes(serialized_summary.encode("ascii")):
            raise RegistryConflict("result artifact hash does not match the canonical summary")
        started = time.perf_counter_ns()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT canonical_summary_json, result_artifact_id, status
                FROM experiment_registry
                WHERE experiment_id = ?
                """,
                (experiment_id,),
            ).fetchone()
            if existing is not None:
                stored_summary, stored_artifact_id, status = existing
                if status != "completed":
                    raise RegistryConflict("a prior experiment record is not completed")
                if stored_summary != serialized_summary or stored_artifact_id != result_artifact_id:
                    raise RegistryConflict("experiment identity maps to different durable output")
                self._record_a0_lineage_locked(
                    connection,
                    experiment_id=experiment_id,
                    trial_id=trial_id,
                    strategy_family_id=strategy_family_id,
                    dataset_identity=dataset_identity,
                    dataset_sha256=dataset_sha256,
                    code_sha256=code_sha256,
                    config_sha256=config_sha256,
                    result_artifact_id=result_artifact_id,
                    created_at_ns=started_at_ns,
                )
                connection.execute("COMMIT")
                return RegistryRecord(
                    canonical_summary=json.loads(stored_summary),
                    result_artifact_id=stored_artifact_id,
                    reused=True,
                    sqlite_write_elapsed_ns=0,
                    sqlite_read_elapsed_ns=max(1, time.perf_counter_ns() - started),
                )

            connection.execute(
                """
                INSERT INTO experiment_registry (
                    experiment_id, trial_id, strategy_family_id, dataset_path,
                    dataset_identity, dataset_sha256, code_sha256, config_sha256,
                    started_at_ns, finished_at_ns, status, result_artifact_id,
                    canonical_summary_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?)
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
                    started_at_ns,
                    finished_at_ns,
                    result_artifact_id,
                    serialized_summary,
                ),
            )
            self._record_a0_lineage_locked(
                connection,
                experiment_id=experiment_id,
                trial_id=trial_id,
                strategy_family_id=strategy_family_id,
                dataset_identity=dataset_identity,
                dataset_sha256=dataset_sha256,
                code_sha256=code_sha256,
                config_sha256=config_sha256,
                result_artifact_id=result_artifact_id,
                created_at_ns=started_at_ns,
            )
            connection.execute("COMMIT")
            return RegistryRecord(
                canonical_summary=canonical_summary,
                result_artifact_id=result_artifact_id,
                reused=False,
                sqlite_write_elapsed_ns=max(1, time.perf_counter_ns() - started),
                sqlite_read_elapsed_ns=0,
            )
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError as error:
            self._rollback(connection)
            raise RegistryConflict("experiment lineage integrity rejected") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry writer is already held by another process") from error
        finally:
            connection.close()

    def record_contract_bundle(
        self,
        artifacts: Iterable[LineageArtifact],
        relations: Iterable[tuple[str, str]],
    ) -> LineageBundleResult:
        """Record a future-stage contract bundle without claiming a runtime producer exists."""
        artifact_items = tuple(artifacts)
        relation_items = tuple(relations)
        if not artifact_items:
            raise RegistryConflict("lineage bundle requires at least one artifact")
        if len({item.artifact_id for item in artifact_items}) != len(artifact_items):
            raise RegistryConflict("lineage bundle contains duplicate artifact identities")
        if len(set(relation_items)) != len(relation_items):
            raise RegistryConflict("lineage bundle contains duplicate relations")

        started = time.perf_counter_ns()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            changed = False
            resolved_artifact_ids: dict[str, str] = {}
            for artifact in artifact_items:
                ensured = self._ensure_artifact_locked(connection, artifact, time.time_ns())
                resolved_artifact_ids[artifact.artifact_id] = ensured.artifact_id
                changed = ensured.changed or changed
            for parent_artifact_id, child_artifact_id in relation_items:
                changed = (
                    self._ensure_relation_locked(
                        connection,
                        resolved_artifact_ids.get(parent_artifact_id, parent_artifact_id),
                        resolved_artifact_ids.get(child_artifact_id, child_artifact_id),
                        time.time_ns(),
                    )
                    or changed
                )
            connection.execute("COMMIT")
            elapsed = max(1, time.perf_counter_ns() - started)
            return LineageBundleResult(
                artifact_ids=tuple(resolved_artifact_ids[item.artifact_id] for item in artifact_items),
                reused=not changed,
                sqlite_write_elapsed_ns=elapsed if changed else 0,
                sqlite_read_elapsed_ns=0 if changed else elapsed,
            )
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError as error:
            self._rollback(connection)
            raise RegistryConflict("lineage contract integrity rejected") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry writer is already held by another process") from error
        finally:
            connection.close()

    @staticmethod
    def decode_h1_opaque_evidence(
        encoded: str,
        expected_sha256: str,
    ) -> bytes:
        """Strictly decode task-local C3 bytes without interpreting their document."""
        _require_sha256(expected_sha256, "opaque evidence expected_sha256")
        if not isinstance(encoded, str) or not encoded:
            raise RegistryConflict("opaque evidence base64 must be a non-empty string")
        try:
            raw = _strict_rfc4648_base64_decode(encoded)
        except ValueError as error:
            raise RegistryConflict("opaque evidence is not strict RFC4648 base64") from error
        if not raw:
            raise RegistryConflict("opaque evidence must not be empty")
        if sha256_bytes(raw) != expected_sha256:
            raise RegistryConflict("opaque evidence SHA-256 does not match")
        return raw

    def record_h1_lineage(
        self,
        *,
        opaque_c3_bytes: bytes,
        opaque_c3_sha256: str,
        c3_task_uuid: str,
        c3_result_uuid: str,
        c3_result_raw_sha256: str,
        c3_exporter_commit: str,
        c2_canonical_wire_sha256: str,
        c2_materialization_id: str,
        c0_data_snapshot_id: str,
        c0_experiment_run_id: str,
        c0_candidate_id: str,
        c0_package_id: str,
        c0_trace_id: str,
        c0_strategy_family_id: str,
        c0_code_sha256: str,
        c0_config_sha256: str,
        recorded_at_ns: int,
    ) -> H1LineageResult:
        """Atomically materialize one real, opaque-source H1 lineage chain.

        The C3 bytes are intentionally never decoded as JSON or regenerated.
        Their sole use here is byte-level hashing and durable BLOB persistence.
        """
        self._validate_h1_input(
            opaque_c3_bytes=opaque_c3_bytes,
            opaque_c3_sha256=opaque_c3_sha256,
            c3_task_uuid=c3_task_uuid,
            c3_result_uuid=c3_result_uuid,
            c3_result_raw_sha256=c3_result_raw_sha256,
            c3_exporter_commit=c3_exporter_commit,
            c2_canonical_wire_sha256=c2_canonical_wire_sha256,
            c2_materialization_id=c2_materialization_id,
            c0_data_snapshot_id=c0_data_snapshot_id,
            c0_experiment_run_id=c0_experiment_run_id,
            c0_candidate_id=c0_candidate_id,
            c0_package_id=c0_package_id,
            c0_trace_id=c0_trace_id,
            c0_strategy_family_id=c0_strategy_family_id,
            c0_code_sha256=c0_code_sha256,
            c0_config_sha256=c0_config_sha256,
            recorded_at_ns=recorded_at_ns,
        )
        lineage_id = self._h1_lineage_identifier(
            opaque_c3_sha256=opaque_c3_sha256,
            c0_data_snapshot_id=c0_data_snapshot_id,
            c0_experiment_run_id=c0_experiment_run_id,
            c0_candidate_id=c0_candidate_id,
            c0_package_id=c0_package_id,
            c0_trace_id=c0_trace_id,
            c0_strategy_family_id=c0_strategy_family_id,
            c0_code_sha256=c0_code_sha256,
            c0_config_sha256=c0_config_sha256,
            c2_materialization_id=c2_materialization_id,
        )
        artifacts = self._h1_lineage_artifacts(
            lineage_id=lineage_id,
            opaque_c3_sha256=opaque_c3_sha256,
            c3_task_uuid=c3_task_uuid,
            c3_result_uuid=c3_result_uuid,
            c3_result_raw_sha256=c3_result_raw_sha256,
            c3_exporter_commit=c3_exporter_commit,
            c2_canonical_wire_sha256=c2_canonical_wire_sha256,
            c2_materialization_id=c2_materialization_id,
            c0_data_snapshot_id=c0_data_snapshot_id,
            c0_experiment_run_id=c0_experiment_run_id,
            c0_candidate_id=c0_candidate_id,
            c0_package_id=c0_package_id,
            c0_trace_id=c0_trace_id,
            c0_strategy_family_id=c0_strategy_family_id,
            c0_code_sha256=c0_code_sha256,
            c0_config_sha256=c0_config_sha256,
        )
        started = time.perf_counter_ns()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._preflight_migration_state(connection, self._migration_digests())
            self._require_h1_migration_locked(connection)
            self._validate_persisted_h1(connection)
            changed = self._ensure_h1_raw_evidence_locked(
                connection,
                opaque_c3_bytes=opaque_c3_bytes,
                opaque_c3_sha256=opaque_c3_sha256,
                c3_task_uuid=c3_task_uuid,
                c3_result_uuid=c3_result_uuid,
                c3_result_raw_sha256=c3_result_raw_sha256,
                c3_exporter_commit=c3_exporter_commit,
                c2_canonical_wire_sha256=c2_canonical_wire_sha256,
                c2_materialization_id=c2_materialization_id,
                recorded_at_ns=recorded_at_ns,
            )
            for artifact in artifacts:
                ensured = self._ensure_artifact_locked(connection, artifact, recorded_at_ns)
                changed = ensured.changed or changed
            artifact_ids = tuple(item.artifact_id for item in artifacts)
            for parent_id, child_id in zip(artifact_ids, artifact_ids[1:]):
                changed = (
                    self._ensure_relation_locked(connection, parent_id, child_id, recorded_at_ns)
                    or changed
                )
            changed = (
                self._ensure_h1_materialization_locked(
                    connection,
                    lineage_id=lineage_id,
                    opaque_c3_sha256=opaque_c3_sha256,
                    artifact_ids=artifact_ids,
                    c0_data_snapshot_id=c0_data_snapshot_id,
                    c0_experiment_run_id=c0_experiment_run_id,
                    c0_candidate_id=c0_candidate_id,
                    c0_package_id=c0_package_id,
                    c0_trace_id=c0_trace_id,
                    c0_strategy_family_id=c0_strategy_family_id,
                    c0_code_sha256=c0_code_sha256,
                    c0_config_sha256=c0_config_sha256,
                    recorded_at_ns=recorded_at_ns,
                )
                or changed
            )
            self._validate_persisted_h1(connection)
            connection.execute("COMMIT")
            elapsed = max(1, time.perf_counter_ns() - started)
            return H1LineageResult(
                lineage_id=lineage_id,
                opaque_evidence_sha256=opaque_c3_sha256,
                artifact_ids=artifact_ids,
                reused=not changed,
                sqlite_write_elapsed_ns=elapsed if changed else 0,
                sqlite_read_elapsed_ns=0 if changed else elapsed,
            )
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError as error:
            self._rollback(connection)
            raise RegistryConflict("H1 immutable lineage integrity rejected") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("H1 lineage writer is already held by another process") from error
        finally:
            connection.close()

    def read_h1_lineage(self, lineage_id: str) -> H1LineageReadback:
        """Read an exact H1 materialization only after fail-closed verification."""
        _require_sha256(lineage_id, "H1 lineage_id")
        connection = self._connect()
        try:
            self._preflight_migration_state(connection, self._migration_digests())
            self._require_h1_migration_locked(connection)
            self._validate_persisted_h1(connection)
            row = connection.execute(
                """
                SELECT materialization.opaque_evidence_sha256, evidence.raw_bytes,
                       materialization.data_snapshot_artifact_id,
                       materialization.experiment_run_artifact_id,
                       materialization.strategy_candidate_artifact_id,
                       materialization.strategy_package_artifact_id,
                       materialization.replay_artifact_id,
                       materialization.paper_artifact_id,
                       materialization.decision_artifact_id
                FROM h1_lineage_materializations AS materialization
                JOIN h1_raw_lineage_evidence AS evidence
                  ON evidence.opaque_evidence_sha256 = materialization.opaque_evidence_sha256
                WHERE materialization.lineage_id = ?
                """,
                (lineage_id,),
            ).fetchone()
            if row is None:
                raise RegistryConflict("H1 lineage materialization is missing")
            opaque_evidence_sha256, opaque_bytes, *artifact_ids = tuple(row)
            if type(opaque_bytes) is not bytes:
                raise RegistryConflict("stored H1 opaque evidence is not a BLOB")
            return H1LineageReadback(
                lineage_id=lineage_id,
                opaque_evidence_sha256=opaque_evidence_sha256,
                opaque_bytes=opaque_bytes,
                artifact_ids=tuple(artifact_ids),
            )
        finally:
            connection.close()

    def verify_h1_lineage(self) -> None:
        """Verify all H1 BLOB/provenance/chain bindings without mutating them."""
        connection = self._connect()
        try:
            self._preflight_migration_state(connection, self._migration_digests())
            self._require_h1_migration_locked(connection)
            self._validate_persisted_h1(connection)
        finally:
            connection.close()

    def record_trial_identity(
        self,
        *,
        strategy_family_id: str,
        data_snapshot_artifact_id: str,
        dataset_sha256: str,
        code_sha256: str,
        config_sha256: str,
        created_at_ns: int,
    ) -> TrialIdentityResult:
        """Atomically record or exactly replay one content-addressed D0 trial."""
        _require_nonempty(strategy_family_id, "strategy_family_id")
        _require_sha256(data_snapshot_artifact_id, "data_snapshot_artifact_id")
        _require_sha256(dataset_sha256, "dataset_sha256")
        _require_sha256(code_sha256, "code_sha256")
        _require_sha256(config_sha256, "config_sha256")
        _require_nonnegative_integer(created_at_ns, "created_at_ns")

        identity = {
            "code_sha256": code_sha256,
            "config_sha256": config_sha256,
            "data_snapshot_artifact_id": data_snapshot_artifact_id,
            "dataset_sha256": dataset_sha256,
            "strategy_family_id": strategy_family_id,
        }
        trial_id = sha256_bytes(canonical_bytes(identity))
        started = time.perf_counter_ns()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            expected = (
                strategy_family_id,
                data_snapshot_artifact_id,
                dataset_sha256,
                code_sha256,
                config_sha256,
                trial_id,
            )
            existing = connection.execute(
                """
                SELECT strategy_family_id, data_snapshot_artifact_id, dataset_sha256,
                       code_sha256, config_sha256, identity_sha256
                FROM trial_identities WHERE trial_id = ?
                """,
                (trial_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != expected:
                    raise RegistryConflict("trial identifier maps to different immutable evidence")
                initial_stage = connection.execute(
                    """
                    SELECT from_stage, evidence_artifact_id FROM trial_stage_transitions
                    WHERE trial_id = ? AND to_stage = 'EXPLORATORY'
                    """,
                    (trial_id,),
                ).fetchone()
                if initial_stage is None or tuple(initial_stage) != (None, data_snapshot_artifact_id):
                    raise RegistryConflict("trial identity is missing its immutable exploratory stage")
                count = self._trial_count_locked(
                    connection,
                    strategy_family_id,
                    data_snapshot_artifact_id,
                    dataset_sha256,
                )
                connection.execute("COMMIT")
                return TrialIdentityResult(
                    trial_id=trial_id,
                    trial_count=count,
                    reused=True,
                    sqlite_write_elapsed_ns=0,
                    sqlite_read_elapsed_ns=max(1, time.perf_counter_ns() - started),
                )

            natural = connection.execute(
                """
                SELECT trial_id, identity_sha256 FROM trial_identities
                WHERE strategy_family_id = ?
                  AND data_snapshot_artifact_id = ?
                  AND dataset_sha256 = ?
                  AND code_sha256 = ?
                  AND config_sha256 = ?
                """,
                (
                    strategy_family_id,
                    data_snapshot_artifact_id,
                    dataset_sha256,
                    code_sha256,
                    config_sha256,
                ),
            ).fetchone()
            if natural is not None:
                raise RegistryConflict("trial evidence maps to a non-canonical immutable identifier")

            self._require_matching_data_snapshot_locked(
                connection,
                data_snapshot_artifact_id,
                dataset_sha256,
            )
            self._ensure_trial_locked(connection, trial_id, strategy_family_id, created_at_ns)
            connection.execute(
                """
                INSERT INTO trial_identities (
                    trial_id, strategy_family_id, data_snapshot_artifact_id,
                    dataset_sha256, code_sha256, config_sha256, identity_sha256,
                    created_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trial_id,
                    strategy_family_id,
                    data_snapshot_artifact_id,
                    dataset_sha256,
                    code_sha256,
                    config_sha256,
                    trial_id,
                    created_at_ns,
                ),
            )
            self._ensure_stage_transition_locked(
                connection,
                trial_id=trial_id,
                from_stage=None,
                to_stage="EXPLORATORY",
                evidence_artifact_id=data_snapshot_artifact_id,
                recorded_at_ns=created_at_ns,
            )
            count = self._trial_count_locked(
                connection,
                strategy_family_id,
                data_snapshot_artifact_id,
                dataset_sha256,
            )
            connection.execute("COMMIT")
            return TrialIdentityResult(
                trial_id=trial_id,
                trial_count=count,
                reused=False,
                sqlite_write_elapsed_ns=max(1, time.perf_counter_ns() - started),
                sqlite_read_elapsed_ns=0,
            )
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError as error:
            self._rollback(connection)
            raise RegistryConflict("trial identity integrity rejected") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry writer is already held by another process") from error
        finally:
            connection.close()

    def record_holdout_access(
        self,
        *,
        trial_id: str,
        evidence_artifact_id: str,
        accessed_at_ns: int,
    ) -> HoldoutAccessResult:
        """Append one immutable holdout-access event, or reuse its exact replay."""
        _require_sha256(trial_id, "trial_id")
        _require_sha256(evidence_artifact_id, "evidence_artifact_id")
        _require_nonnegative_integer(accessed_at_ns, "accessed_at_ns")
        holdout_access_id = sha256_bytes(
            canonical_bytes(
                {
                    "accessed_at_ns": accessed_at_ns,
                    "evidence_artifact_id": evidence_artifact_id,
                    "trial_id": trial_id,
                }
            )
        )
        started = time.perf_counter_ns()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_holdout_snapshot_evidence_locked(
                connection,
                trial_id,
                evidence_artifact_id,
            )
            expected = (trial_id, evidence_artifact_id, accessed_at_ns)
            existing = connection.execute(
                """
                SELECT trial_id, evidence_artifact_id, accessed_at_ns
                FROM holdout_accesses WHERE holdout_access_id = ?
                """,
                (holdout_access_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != expected:
                    raise RegistryConflict("holdout access identifier maps to different immutable evidence")
                connection.execute("COMMIT")
                return HoldoutAccessResult(
                    holdout_access_id=holdout_access_id,
                    reused=True,
                    sqlite_write_elapsed_ns=0,
                    sqlite_read_elapsed_ns=max(1, time.perf_counter_ns() - started),
                )
            natural = connection.execute(
                """
                SELECT holdout_access_id FROM holdout_accesses
                WHERE trial_id = ? AND evidence_artifact_id = ? AND accessed_at_ns = ?
                """,
                expected,
            ).fetchone()
            if natural is not None:
                raise RegistryConflict("holdout access maps to a non-canonical immutable identifier")
            connection.execute(
                """
                INSERT INTO holdout_accesses (
                    holdout_access_id, trial_id, evidence_artifact_id, accessed_at_ns
                ) VALUES (?, ?, ?, ?)
                """,
                (holdout_access_id, *expected),
            )
            connection.execute("COMMIT")
            return HoldoutAccessResult(
                holdout_access_id=holdout_access_id,
                reused=False,
                sqlite_write_elapsed_ns=max(1, time.perf_counter_ns() - started),
                sqlite_read_elapsed_ns=0,
            )
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError as error:
            self._rollback(connection)
            raise RegistryConflict("holdout access integrity rejected") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry writer is already held by another process") from error
        finally:
            connection.close()

    def record_overfitting_assessment(
        self,
        *,
        trial_id: str,
        evidence_artifact_id: str,
        evidence: OverfittingEvidence,
        recorded_at_ns: int,
    ) -> OverfittingAssessmentResult:
        """Persist one passing D proof, or return only its exact immutable replay.

        The calculation is intentionally outside the exploratory runner.  This
        transaction binds the proof to an already-completed immutable run and
        the deterministic family/dataset trial count observed at assessment
        time; a later additional trial therefore invalidates it for a *new*
        promotion until new evidence is recorded.
        """
        _require_sha256(trial_id, "trial_id")
        _require_sha256(evidence_artifact_id, "evidence_artifact_id")
        _require_nonnegative_integer(recorded_at_ns, "recorded_at_ns")
        from .overfitting import (
            OverfittingEvidence,
            OverfittingValidationError,
            validate_and_canonicalize,
        )

        if not isinstance(evidence, OverfittingEvidence):
            raise RegistryConflict("overfitting evidence has an unsupported type")

        started = time.perf_counter_ns()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_d_migration_locked(connection)
            self._validate_persisted_d(connection)
            self._require_trial_bound_stage_evidence_locked(
                connection,
                trial_id,
                evidence_artifact_id,
            )
            self._reject_holdout_for_overfitting_locked(connection, trial_id)
            identity = connection.execute(
                """
                SELECT strategy_family_id, data_snapshot_artifact_id, dataset_sha256, created_at_ns
                FROM trial_identities WHERE trial_id = ?
                """,
                (trial_id,),
            ).fetchone()
            if identity is None:
                raise RegistryConflict("overfitting assessment trial identity is missing")
            strategy_family_id, data_snapshot_artifact_id, dataset_sha256, created_at_ns = tuple(identity)
            if recorded_at_ns < created_at_ns:
                raise RegistryConflict("overfitting assessment predates its immutable trial identity")
            trial_count = self._trial_count_at_locked(
                connection,
                strategy_family_id,
                data_snapshot_artifact_id,
                dataset_sha256,
                recorded_at_ns,
            )
            try:
                canonical_evidence = validate_and_canonicalize(evidence, trial_count)
            except OverfittingValidationError as error:
                raise RegistryConflict("overfitting evidence failed closed") from error
            evidence_json = canonical_bytes(canonical_evidence).decode("ascii")
            evidence_sha256 = sha256_bytes(evidence_json.encode("ascii"))
            policy_sha256 = canonical_evidence["policy_sha256"]
            assessment_id = self._assessment_identifier(
                trial_id,
                evidence_artifact_id,
                trial_count,
                policy_sha256,
                evidence_sha256,
                recorded_at_ns,
            )
            expected = (
                trial_id,
                evidence_artifact_id,
                trial_count,
                policy_sha256,
                evidence_json,
                evidence_sha256,
                recorded_at_ns,
                1,
            )
            existing = connection.execute(
                """
                SELECT trial_id, evidence_artifact_id, trial_count, policy_sha256,
                       canonical_evidence_json, evidence_sha256, recorded_at_ns, passed
                FROM overfitting_assessments WHERE assessment_id = ?
                """,
                (assessment_id,),
            ).fetchone()
            if existing is not None:
                if tuple(existing) != expected:
                    raise RegistryConflict("overfitting assessment identifier maps to different immutable proof")
                connection.execute("COMMIT")
                return OverfittingAssessmentResult(
                    assessment_id=assessment_id,
                    trial_id=trial_id,
                    evidence_artifact_id=evidence_artifact_id,
                    trial_count=trial_count,
                    policy_sha256=policy_sha256,
                    reused=True,
                    sqlite_write_elapsed_ns=0,
                    sqlite_read_elapsed_ns=max(1, time.perf_counter_ns() - started),
                )
            natural = connection.execute(
                """
                SELECT assessment_id FROM overfitting_assessments
                WHERE trial_id = ? AND evidence_artifact_id = ?
                """,
                (trial_id, evidence_artifact_id),
            ).fetchone()
            if natural is not None:
                raise RegistryConflict("trial/run already has a different immutable overfitting assessment")
            connection.execute(
                """
                INSERT INTO overfitting_assessments (
                    assessment_id, trial_id, evidence_artifact_id, trial_count,
                    policy_sha256, canonical_evidence_json, evidence_sha256,
                    recorded_at_ns, passed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    assessment_id,
                    trial_id,
                    evidence_artifact_id,
                    trial_count,
                    policy_sha256,
                    evidence_json,
                    evidence_sha256,
                    recorded_at_ns,
                ),
            )
            connection.execute("COMMIT")
            return OverfittingAssessmentResult(
                assessment_id=assessment_id,
                trial_id=trial_id,
                evidence_artifact_id=evidence_artifact_id,
                trial_count=trial_count,
                policy_sha256=policy_sha256,
                reused=False,
                sqlite_write_elapsed_ns=max(1, time.perf_counter_ns() - started),
                sqlite_read_elapsed_ns=0,
            )
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError as error:
            self._rollback(connection)
            raise RegistryConflict("overfitting assessment integrity rejected") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry writer is already held by another process") from error
        finally:
            connection.close()

    def verify_overfitting_assessments(self) -> None:
        """Explicitly audit all persisted D proofs without touching the runner path.

        ``run_experiment`` deliberately calls only ``initialize`` and never
        imports or scans D evidence.  Promotion and D writes already perform
        this audit fail-closed; callers that need a complete offline integrity
        audit can invoke this method explicitly.
        """
        connection = self._connect()
        try:
            self._require_d_migration_locked(connection)
            self._assert_database_integrity(connection)
            self._validate_persisted_d(connection)
        finally:
            connection.close()

    def advance_trial_stage(
        self,
        *,
        trial_id: str,
        to_stage: str,
        evidence_artifact_id: str,
        recorded_at_ns: int,
    ) -> TrialStageResult:
        """Append the next allowed D0 stage or exactly replay a prior stage event."""
        _require_sha256(trial_id, "trial_id")
        _require_sha256(evidence_artifact_id, "evidence_artifact_id")
        _require_nonnegative_integer(recorded_at_ns, "recorded_at_ns")
        if to_stage not in _TRIAL_STAGE_PREDECESSOR:
            raise RegistryConflict("D0 stage advancement must target candidate-or-higher stage")
        from_stage = _TRIAL_STAGE_PREDECESSOR[to_stage]
        started = time.perf_counter_ns()
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT stage_transition_id, from_stage, evidence_artifact_id, recorded_at_ns
                FROM trial_stage_transitions
                WHERE trial_id = ? AND to_stage = ?
                """,
                (trial_id, to_stage),
            ).fetchone()
            expected_id = self._stage_transition_identifier(
                trial_id,
                from_stage,
                to_stage,
                evidence_artifact_id,
                recorded_at_ns,
            )
            expected = (expected_id, from_stage, evidence_artifact_id, recorded_at_ns)
            if existing is not None:
                if tuple(existing) != expected:
                    raise RegistryConflict("trial stage maps to different immutable evidence")
                connection.execute("COMMIT")
                return TrialStageResult(
                    stage_transition_id=expected_id,
                    trial_id=trial_id,
                    stage=to_stage,
                    reused=True,
                    sqlite_write_elapsed_ns=0,
                    sqlite_read_elapsed_ns=max(1, time.perf_counter_ns() - started),
                )
            self._require_trial_bound_stage_evidence_locked(
                connection,
                trial_id,
                evidence_artifact_id,
            )
            self._require_passed_overfitting_assessment_locked(
                connection,
                trial_id,
                evidence_artifact_id,
            )
            current_stage = self._current_trial_stage_locked(connection, trial_id)
            if current_stage != from_stage:
                raise RegistryConflict("trial stage transition does not follow the current immutable stage")
            self._ensure_stage_transition_locked(
                connection,
                trial_id=trial_id,
                from_stage=from_stage,
                to_stage=to_stage,
                evidence_artifact_id=evidence_artifact_id,
                recorded_at_ns=recorded_at_ns,
            )
            connection.execute("COMMIT")
            return TrialStageResult(
                stage_transition_id=expected_id,
                trial_id=trial_id,
                stage=to_stage,
                reused=False,
                sqlite_write_elapsed_ns=max(1, time.perf_counter_ns() - started),
                sqlite_read_elapsed_ns=0,
            )
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.IntegrityError as error:
            self._rollback(connection)
            raise RegistryConflict("trial stage integrity rejected") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry writer is already held by another process") from error
        finally:
            connection.close()

    def rollback_lineage_for_disposable_fixture(self) -> None:
        """Reverse A1/H0 migrations only in a marked temporary test fixture."""
        self._require_disposable_rollback_fixture()
        rollback_path = self._migration_dir / "rollback" / _LINEAGE_MIGRATION
        raw = self._read_migration(rollback_path)
        connection = self._connect()
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                raise RegistryBusy("registry rollback could not acquire the writer lock") from error
            self._reject_d0_rollback_locked(connection)
            compatibility_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
                (_COMPATIBILITY_MIGRATION,),
            ).fetchone()
            if compatibility_applied is not None:
                self._rollback_compatibility_locked(connection)
            applied = connection.execute(
                "SELECT migration_sha256 FROM schema_migrations WHERE migration_name = ?",
                (_LINEAGE_MIGRATION,),
            ).fetchone()
            if applied is None:
                raise RegistryConflict("lineage migration is not applied")
            self._execute_sql_script(connection, raw.decode("utf-8"))
            connection.execute(
                "DELETE FROM schema_migrations WHERE migration_name = ?",
                (_LINEAGE_MIGRATION,),
            )
            connection.execute("COMMIT")
        except RegistryConflict:
            self._rollback(connection)
            raise
        except UnicodeDecodeError as error:
            self._rollback(connection)
            raise RegistryConflict("rollback migration must be UTF-8 text") from error
        except sqlite3.Error as error:
            self._rollback(connection)
            raise RegistryConflict("lineage rollback failed closed") from error
        finally:
            connection.close()

    def rollback_compatibility_for_disposable_fixture(self) -> None:
        """Reverse only 003 trigger convergence in a marked temporary fixture."""
        self._require_disposable_rollback_fixture()
        connection = self._connect()
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as error:
                raise RegistryBusy("compatibility rollback could not acquire the writer lock") from error
            self._reject_d0_rollback_locked(connection)
            self._rollback_compatibility_locked(connection)
            connection.execute("COMMIT")
        except RegistryConflict:
            self._rollback(connection)
            raise
        except sqlite3.Error as error:
            self._rollback(connection)
            raise RegistryConflict("compatibility rollback failed closed") from error
        finally:
            connection.close()

    def _rollback_compatibility_locked(self, connection: sqlite3.Connection) -> None:
        """Restore the exact pre-003 trigger state without touching lineage data."""
        self._reject_d0_rollback_locked(connection)
        migration_digests = self._migration_digests()
        self._preflight_migration_state(connection, migration_digests)
        marker = connection.execute(
            "SELECT migration_sha256 FROM schema_migrations WHERE migration_name = ?",
            (_LINEAGE_MIGRATION,),
        ).fetchone()
        compatibility = connection.execute(
            "SELECT migration_sha256 FROM schema_migrations WHERE migration_name = ?",
            (_COMPATIBILITY_MIGRATION,),
        ).fetchone()
        if marker is None or compatibility is None:
            raise RegistryConflict("compatibility migration is not applied")

        if marker[0] == _LEGACY_F36_LINEAGE_SHA256:
            for trigger_name in _COMPATIBILITY_HARDENING_TRIGGERS:
                connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
            self._execute_sql_script(connection, _LEGACY_F36_RELATION_TRIGGER_SQL)
        elif marker[0] == migration_digests.get(_LINEAGE_MIGRATION):
            connection.execute("DROP TRIGGER IF EXISTS schema_migrations_no_delete")
        else:
            raise RegistryConflict("compatibility rollback does not recognize the 002 marker")

        connection.execute(
            "DELETE FROM schema_migrations WHERE migration_name = ?",
            (_COMPATIBILITY_MIGRATION,),
        )
        if marker[0] == migration_digests.get(_LINEAGE_MIGRATION):
            self._execute_sql_script(connection, _SCHEMA_MIGRATIONS_NO_DELETE_TRIGGER_SQL)
        self._preflight_migration_state(connection, migration_digests)

    @staticmethod
    def _reject_d0_rollback_locked(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
            (_D0_MIGRATION,),
        ).fetchone() is not None:
            raise RegistryConflict("D0 migration is forward-only and cannot be rolled back")

    def _record_a0_lineage_locked(
        self,
        connection: sqlite3.Connection,
        *,
        experiment_id: str,
        trial_id: str,
        strategy_family_id: str,
        dataset_identity: str,
        dataset_sha256: str,
        code_sha256: str,
        config_sha256: str,
        result_artifact_id: str,
        created_at_ns: int,
    ) -> None:
        """Record only A0's proven DataSnapshot -> ExperimentRun evidence."""
        snapshot = LineageArtifact(
            artifact_type="DataSnapshot",
            identity_sha256=dataset_identity,
            content_sha256=dataset_sha256,
            payload={
                "dataset_identity": dataset_identity,
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
        resolved_snapshot = self._ensure_artifact_locked(connection, snapshot, created_at_ns)
        resolved_experiment_run = self._ensure_artifact_locked(connection, experiment_run, created_at_ns)
        self._ensure_relation_locked(
            connection,
            resolved_snapshot.artifact_id,
            resolved_experiment_run.artifact_id,
            created_at_ns,
        )
        self._ensure_trial_locked(connection, trial_id, strategy_family_id, created_at_ns)
        self._ensure_experiment_locked(
            connection,
            experiment_id=experiment_id,
            trial_id=trial_id,
            data_snapshot_artifact_id=resolved_snapshot.artifact_id,
            experiment_run_artifact_id=resolved_experiment_run.artifact_id,
            code_sha256=code_sha256,
            config_sha256=config_sha256,
            result_artifact_id=result_artifact_id,
            created_at_ns=created_at_ns,
        )

    def _ensure_artifact_locked(
        self,
        connection: sqlite3.Connection,
        artifact: LineageArtifact,
        created_at_ns: int,
    ) -> _ArtifactEnsureResult:
        existing = connection.execute(
            """
            SELECT artifact_type, identity_sha256, content_sha256, canonical_payload_json
            FROM artifacts WHERE artifact_id = ?
            """,
            (artifact.artifact_id,),
        ).fetchone()
        expected = (
            artifact.artifact_type,
            artifact.identity_sha256,
            artifact.content_sha256,
            artifact.canonical_payload_json,
        )
        if existing is not None:
            if tuple(existing) != expected:
                raise RegistryConflict("artifact identifier maps to different immutable content")
            return _ArtifactEnsureResult(artifact.artifact_id, False)

        natural = connection.execute(
            """
            SELECT artifact_id, content_sha256, canonical_payload_json
            FROM artifacts WHERE artifact_type = ? AND identity_sha256 = ?
            """,
            (artifact.artifact_type, artifact.identity_sha256),
        ).fetchone()
        if natural is not None:
            legacy_artifact_id = self._resolve_legacy_a0_snapshot_artifact_id(
                connection,
                artifact,
                natural,
            )
            if legacy_artifact_id is not None:
                return _ArtifactEnsureResult(legacy_artifact_id, False)
            if (
                natural[0] != artifact.artifact_id
                or natural[1] != artifact.content_sha256
                or natural[2] != artifact.canonical_payload_json
            ):
                raise RegistryConflict("artifact identity maps to different immutable content")
            return _ArtifactEnsureResult(artifact.artifact_id, False)

        connection.execute(
            """
            INSERT INTO artifacts (
                artifact_id, artifact_type, identity_sha256, content_sha256,
                canonical_payload_json, created_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.artifact_type,
                artifact.identity_sha256,
                artifact.content_sha256,
                artifact.canonical_payload_json,
                created_at_ns,
            ),
        )
        return _ArtifactEnsureResult(artifact.artifact_id, True)

    @staticmethod
    def _resolve_legacy_a0_snapshot_artifact_id(
        connection: sqlite3.Connection,
        artifact: LineageArtifact,
        natural: Any,
    ) -> str | None:
        """Reuse only a self-consistent f36 A0 snapshot without rewriting it."""
        if artifact.artifact_type != "DataSnapshot":
            return None
        marker = connection.execute(
            "SELECT migration_sha256 FROM schema_migrations WHERE migration_name = ?",
            (_LINEAGE_MIGRATION,),
        ).fetchone()
        if marker is None or marker[0] != _LEGACY_F36_LINEAGE_SHA256:
            return None

        artifact_id, content_sha256, payload_json = natural
        if content_sha256 != artifact.content_sha256:
            return None
        try:
            payload = json.loads(payload_json)
        except (TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or canonical_bytes(payload).decode("ascii") != payload_json:
            return None
        if set(payload) != {"dataset_identity", "dataset_path", "dataset_sha256"}:
            return None
        if (
            payload["dataset_identity"] != artifact.identity_sha256
            or payload["dataset_sha256"] != artifact.content_sha256
            or not isinstance(payload["dataset_path"], str)
            or not payload["dataset_path"]
        ):
            return None
        try:
            legacy = LineageArtifact(
                artifact_type="DataSnapshot",
                identity_sha256=artifact.identity_sha256,
                content_sha256=artifact.content_sha256,
                payload=payload,
            )
        except RegistryConflict:
            return None
        if legacy.artifact_id != artifact_id:
            return None
        linked = connection.execute(
            """
            SELECT 1
            FROM experiments AS experiment
            JOIN experiment_registry AS registry
              ON registry.experiment_id = experiment.experiment_id
            WHERE experiment.data_snapshot_artifact_id = ?
              AND registry.dataset_identity = ?
              AND registry.dataset_sha256 = ?
              AND registry.dataset_path = ?
            LIMIT 1
            """,
            (
                artifact_id,
                artifact.identity_sha256,
                artifact.content_sha256,
                payload["dataset_path"],
            ),
        ).fetchone()
        return artifact_id if linked is not None else None

    @staticmethod
    def _ensure_relation_locked(
        connection: sqlite3.Connection,
        parent_artifact_id: str,
        child_artifact_id: str,
        created_at_ns: int,
    ) -> bool:
        _require_sha256(parent_artifact_id, "parent_artifact_id")
        _require_sha256(child_artifact_id, "child_artifact_id")
        if parent_artifact_id == child_artifact_id:
            raise RegistryConflict("lineage relation cannot be a self-edge")
        existing = connection.execute(
            """
            SELECT 1 FROM relations
            WHERE parent_artifact_id = ? AND child_artifact_id = ? AND relation_type = 'derives_from'
            """,
            (parent_artifact_id, child_artifact_id),
        ).fetchone()
        if existing is not None:
            return False
        connection.execute(
            """
            INSERT INTO relations (parent_artifact_id, child_artifact_id, relation_type, created_at_ns)
            VALUES (?, ?, 'derives_from', ?)
            """,
            (parent_artifact_id, child_artifact_id, created_at_ns),
        )
        return True

    @staticmethod
    def _ensure_trial_locked(
        connection: sqlite3.Connection,
        trial_id: str,
        strategy_family_id: str,
        created_at_ns: int,
    ) -> bool:
        identity_sha256 = sha256_bytes(
            canonical_bytes(
                {"strategy_family_id": strategy_family_id, "trial_id": trial_id}
            )
        )
        existing = connection.execute(
            "SELECT strategy_family_id, identity_sha256 FROM trials WHERE trial_id = ?",
            (trial_id,),
        ).fetchone()
        expected = (strategy_family_id, identity_sha256)
        if existing is not None:
            if tuple(existing) != expected:
                raise RegistryConflict("trial identifier maps to different immutable content")
            return False
        connection.execute(
            """
            INSERT INTO trials (trial_id, strategy_family_id, identity_sha256, created_at_ns)
            VALUES (?, ?, ?, ?)
            """,
            (trial_id, strategy_family_id, identity_sha256, created_at_ns),
        )
        return True

    @staticmethod
    def _ensure_experiment_locked(
        connection: sqlite3.Connection,
        *,
        experiment_id: str,
        trial_id: str,
        data_snapshot_artifact_id: str,
        experiment_run_artifact_id: str,
        code_sha256: str,
        config_sha256: str,
        result_artifact_id: str,
        created_at_ns: int,
    ) -> bool:
        existing = connection.execute(
            """
            SELECT trial_id, data_snapshot_artifact_id, experiment_run_artifact_id,
                   code_sha256, config_sha256, result_artifact_id
            FROM experiments WHERE experiment_id = ?
            """,
            (experiment_id,),
        ).fetchone()
        expected = (
            trial_id,
            data_snapshot_artifact_id,
            experiment_run_artifact_id,
            code_sha256,
            config_sha256,
            result_artifact_id,
        )
        if existing is not None:
            if tuple(existing) != expected:
                raise RegistryConflict("experiment identifier maps to different immutable lineage")
            return False
        connection.execute(
            """
            INSERT INTO experiments (
                experiment_id, trial_id, data_snapshot_artifact_id,
                experiment_run_artifact_id, code_sha256, config_sha256,
                result_artifact_id, created_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                experiment_id,
                trial_id,
                data_snapshot_artifact_id,
                experiment_run_artifact_id,
                code_sha256,
                config_sha256,
                result_artifact_id,
                created_at_ns,
            ),
        )
        return True

    @staticmethod
    def _validate_h1_input(
        *,
        opaque_c3_bytes: bytes,
        opaque_c3_sha256: str,
        c3_task_uuid: str,
        c3_result_uuid: str,
        c3_result_raw_sha256: str,
        c3_exporter_commit: str,
        c2_canonical_wire_sha256: str,
        c2_materialization_id: str,
        c0_data_snapshot_id: str,
        c0_experiment_run_id: str,
        c0_candidate_id: str,
        c0_package_id: str,
        c0_trace_id: str,
        c0_strategy_family_id: str,
        c0_code_sha256: str,
        c0_config_sha256: str,
        recorded_at_ns: int,
    ) -> None:
        if type(opaque_c3_bytes) is not bytes or not opaque_c3_bytes:
            raise RegistryConflict("opaque C3 evidence must be non-empty bytes")
        _require_sha256(opaque_c3_sha256, "opaque C3 evidence SHA-256")
        if sha256_bytes(opaque_c3_bytes) != opaque_c3_sha256:
            raise RegistryConflict("opaque C3 evidence SHA-256 does not match")
        _require_uuid(c3_task_uuid, "C3 task UUID")
        _require_uuid(c3_result_uuid, "C3 result UUID")
        _require_sha256(c3_result_raw_sha256, "C3 result raw SHA-256")
        _require_git_commit(c3_exporter_commit, "C3 exporter commit")
        _require_sha256(c2_canonical_wire_sha256, "C2 canonical wire SHA-256")
        _require_sha256(c2_materialization_id, "C2 materialization ID")
        _require_sha256(c0_data_snapshot_id, "C0 data snapshot ID")
        _require_sha256(c0_experiment_run_id, "C0 experiment run ID")
        _require_sha256(c0_candidate_id, "C0 candidate ID")
        _require_sha256(c0_package_id, "C0 package ID")
        _require_sha256(c0_trace_id, "C0 trace ID")
        _require_nonempty(c0_strategy_family_id, "C0 strategy family ID")
        _require_sha256(c0_code_sha256, "C0 code SHA-256")
        _require_sha256(c0_config_sha256, "C0 config SHA-256")
        _require_nonnegative_integer(recorded_at_ns, "H1 recorded_at_ns")

    @staticmethod
    def _h1_lineage_identifier(
        *,
        opaque_c3_sha256: str,
        c0_data_snapshot_id: str,
        c0_experiment_run_id: str,
        c0_candidate_id: str,
        c0_package_id: str,
        c0_trace_id: str,
        c0_strategy_family_id: str,
        c0_code_sha256: str,
        c0_config_sha256: str,
        c2_materialization_id: str,
    ) -> str:
        return sha256_bytes(
            canonical_bytes(
                {
                    "c0_candidate_id": c0_candidate_id,
                    "c0_code_sha256": c0_code_sha256,
                    "c0_config_sha256": c0_config_sha256,
                    "c0_data_snapshot_id": c0_data_snapshot_id,
                    "c0_experiment_run_id": c0_experiment_run_id,
                    "c0_package_id": c0_package_id,
                    "c0_strategy_family_id": c0_strategy_family_id,
                    "c0_trace_id": c0_trace_id,
                    "c2_materialization_id": c2_materialization_id,
                    "opaque_c3_sha256": opaque_c3_sha256,
                }
            )
        )

    @staticmethod
    def _h1_lineage_artifact(
        artifact_type: str,
        identity_sha256: str,
        payload: dict[str, Any],
    ) -> LineageArtifact:
        return LineageArtifact(
            artifact_type=artifact_type,
            identity_sha256=identity_sha256,
            content_sha256=sha256_bytes(canonical_bytes(payload)),
            payload=payload,
        )

    @classmethod
    def _h1_lineage_artifacts(
        cls,
        *,
        lineage_id: str,
        opaque_c3_sha256: str,
        c3_task_uuid: str,
        c3_result_uuid: str,
        c3_result_raw_sha256: str,
        c3_exporter_commit: str,
        c2_canonical_wire_sha256: str,
        c2_materialization_id: str,
        c0_data_snapshot_id: str,
        c0_experiment_run_id: str,
        c0_candidate_id: str,
        c0_package_id: str,
        c0_trace_id: str,
        c0_strategy_family_id: str,
        c0_code_sha256: str,
        c0_config_sha256: str,
    ) -> tuple[LineageArtifact, ...]:
        snapshot = cls._h1_lineage_artifact(
            "DataSnapshot",
            c0_data_snapshot_id,
            {
                "external_source_id": c0_data_snapshot_id,
                "external_source_kind": "C0_DATA_SNAPSHOT",
                "h1_lineage_id": lineage_id,
                "source_c2_materialization_id": c2_materialization_id,
            },
        )
        experiment_run = cls._h1_lineage_artifact(
            "ExperimentRun",
            c0_experiment_run_id,
            {
                "external_source_id": c0_experiment_run_id,
                "external_source_kind": "C0_EXPERIMENT_RUN",
                "h1_lineage_id": lineage_id,
                "source_c0_code_sha256": c0_code_sha256,
                "source_c0_config_sha256": c0_config_sha256,
                "source_c2_canonical_wire_sha256": c2_canonical_wire_sha256,
            },
        )
        candidate = cls._h1_lineage_artifact(
            "StrategyCandidate",
            c0_candidate_id,
            {
                "external_source_id": c0_candidate_id,
                "external_source_kind": "C0_STRATEGY_CANDIDATE",
                "h1_lineage_id": lineage_id,
                "source_c0_trace_id": c0_trace_id,
                "strategy_family_id": c0_strategy_family_id,
            },
        )
        package = cls._h1_lineage_artifact(
            "StrategyPackage",
            c0_package_id,
            {
                "external_source_id": c0_package_id,
                "external_source_kind": "C0_STRATEGY_PACKAGE",
                "h1_lineage_id": lineage_id,
                "strategy_family_id": c0_strategy_family_id,
            },
        )
        replay = cls._h1_lineage_artifact(
            "Replay",
            sha256_bytes(
                canonical_bytes(
                    {
                        "c0_trace_id": c0_trace_id,
                        "opaque_c3_sha256": opaque_c3_sha256,
                    }
                )
            ),
            {
                "c3_exporter_commit": c3_exporter_commit,
                "c3_result_raw_sha256": c3_result_raw_sha256,
                "c3_result_uuid": c3_result_uuid,
                "c3_task_uuid": c3_task_uuid,
                "h1_lineage_id": lineage_id,
                "opaque_c3_sha256": opaque_c3_sha256,
                "source_c0_trace_id": c0_trace_id,
            },
        )
        paper = cls._h1_lineage_artifact(
            "Paper",
            sha256_bytes(
                canonical_bytes(
                    {
                        "opaque_c3_sha256": opaque_c3_sha256,
                        "replay_artifact_id": replay.artifact_id,
                    }
                )
            ),
            {
                "boundary": "SIMULATION_ARTIFACT_ONLY",
                "h1_lineage_id": lineage_id,
                "opaque_c3_sha256": opaque_c3_sha256,
                "replay_artifact_id": replay.artifact_id,
            },
        )
        decision = cls._h1_lineage_artifact(
            "Decision",
            sha256_bytes(
                canonical_bytes(
                    {
                        "paper_artifact_id": paper.artifact_id,
                        "opaque_c3_sha256": opaque_c3_sha256,
                    }
                )
            ),
            {
                "decision_kind": "LINEAGE_RETAINED_NOT_PROMOTION",
                "h1_lineage_id": lineage_id,
                "opaque_c3_sha256": opaque_c3_sha256,
                "paper_artifact_id": paper.artifact_id,
            },
        )
        return (snapshot, experiment_run, candidate, package, replay, paper, decision)

    @staticmethod
    def _require_h1_migration_locked(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
            (_H1_MIGRATION,),
        ).fetchone() is None:
            raise RegistryConflict("H1 raw-lineage migration is not applied")

    @staticmethod
    def _ensure_h1_raw_evidence_locked(
        connection: sqlite3.Connection,
        *,
        opaque_c3_bytes: bytes,
        opaque_c3_sha256: str,
        c3_task_uuid: str,
        c3_result_uuid: str,
        c3_result_raw_sha256: str,
        c3_exporter_commit: str,
        c2_canonical_wire_sha256: str,
        c2_materialization_id: str,
        recorded_at_ns: int,
    ) -> bool:
        existing_by_hash = connection.execute(
            """
            SELECT raw_bytes, c3_task_uuid, c3_result_uuid, c3_result_raw_sha256,
                   c3_exporter_commit, c2_canonical_wire_sha256, c2_materialization_id
            FROM h1_raw_lineage_evidence WHERE opaque_evidence_sha256 = ?
            """,
            (opaque_c3_sha256,),
        ).fetchone()
        expected_by_hash = (
            opaque_c3_bytes,
            c3_task_uuid,
            c3_result_uuid,
            c3_result_raw_sha256,
            c3_exporter_commit,
            c2_canonical_wire_sha256,
            c2_materialization_id,
        )
        if existing_by_hash is not None:
            if tuple(existing_by_hash) != expected_by_hash:
                raise RegistryConflict("opaque C3 evidence maps to different immutable provenance")
            return False
        existing_by_result = connection.execute(
            """
            SELECT opaque_evidence_sha256, raw_bytes, c3_task_uuid, c3_result_raw_sha256,
                   c3_exporter_commit, c2_canonical_wire_sha256, c2_materialization_id
            FROM h1_raw_lineage_evidence WHERE c3_result_uuid = ?
            """,
            (c3_result_uuid,),
        ).fetchone()
        expected_by_result = (
            opaque_c3_sha256,
            opaque_c3_bytes,
            c3_task_uuid,
            c3_result_raw_sha256,
            c3_exporter_commit,
            c2_canonical_wire_sha256,
            c2_materialization_id,
        )
        if existing_by_result is not None:
            if tuple(existing_by_result) != expected_by_result:
                raise RegistryConflict("C3 result identity maps to different immutable opaque evidence")
            return False
        connection.execute(
            """
            INSERT INTO h1_raw_lineage_evidence (
                opaque_evidence_sha256, raw_bytes, c3_task_uuid, c3_result_uuid,
                c3_result_raw_sha256, c3_exporter_commit, c2_canonical_wire_sha256,
                c2_materialization_id, created_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                opaque_c3_sha256,
                opaque_c3_bytes,
                c3_task_uuid,
                c3_result_uuid,
                c3_result_raw_sha256,
                c3_exporter_commit,
                c2_canonical_wire_sha256,
                c2_materialization_id,
                recorded_at_ns,
            ),
        )
        return True

    @staticmethod
    def _ensure_h1_materialization_locked(
        connection: sqlite3.Connection,
        *,
        lineage_id: str,
        opaque_c3_sha256: str,
        artifact_ids: tuple[str, ...],
        c0_data_snapshot_id: str,
        c0_experiment_run_id: str,
        c0_candidate_id: str,
        c0_package_id: str,
        c0_trace_id: str,
        c0_strategy_family_id: str,
        c0_code_sha256: str,
        c0_config_sha256: str,
        recorded_at_ns: int,
    ) -> bool:
        if len(artifact_ids) != 7:
            raise RegistryConflict("H1 materialization requires exactly seven artifacts")
        existing = connection.execute(
            """
            SELECT opaque_evidence_sha256, data_snapshot_artifact_id,
                   experiment_run_artifact_id, strategy_candidate_artifact_id,
                   strategy_package_artifact_id, replay_artifact_id,
                   paper_artifact_id, decision_artifact_id, c0_data_snapshot_id,
                   c0_experiment_run_id, c0_candidate_id, c0_package_id,
                   c0_trace_id, c0_strategy_family_id, c0_code_sha256,
                   c0_config_sha256
            FROM h1_lineage_materializations WHERE lineage_id = ?
            """,
            (lineage_id,),
        ).fetchone()
        expected = (
            opaque_c3_sha256,
            *artifact_ids,
            c0_data_snapshot_id,
            c0_experiment_run_id,
            c0_candidate_id,
            c0_package_id,
            c0_trace_id,
            c0_strategy_family_id,
            c0_code_sha256,
            c0_config_sha256,
        )
        if existing is not None:
            if tuple(existing) != expected:
                raise RegistryConflict("H1 lineage identifier maps to different immutable evidence")
            return False
        existing_raw = connection.execute(
            "SELECT lineage_id FROM h1_lineage_materializations WHERE opaque_evidence_sha256 = ?",
            (opaque_c3_sha256,),
        ).fetchone()
        if existing_raw is not None:
            raise RegistryConflict("opaque C3 evidence already maps to another H1 lineage")
        connection.execute(
            """
            INSERT INTO h1_lineage_materializations (
                lineage_id, opaque_evidence_sha256, data_snapshot_artifact_id,
                experiment_run_artifact_id, strategy_candidate_artifact_id,
                strategy_package_artifact_id, replay_artifact_id, paper_artifact_id,
                decision_artifact_id, c0_data_snapshot_id, c0_experiment_run_id,
                c0_candidate_id, c0_package_id, c0_trace_id, c0_strategy_family_id,
                c0_code_sha256, c0_config_sha256, created_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lineage_id,
                opaque_c3_sha256,
                *artifact_ids,
                c0_data_snapshot_id,
                c0_experiment_run_id,
                c0_candidate_id,
                c0_package_id,
                c0_trace_id,
                c0_strategy_family_id,
                c0_code_sha256,
                c0_config_sha256,
                recorded_at_ns,
            ),
        )
        return True

    @classmethod
    def _validate_persisted_h1(cls, connection: sqlite3.Connection) -> None:
        """Fail closed on any opaque BLOB or seven-step materialization drift."""
        cls._validate_persisted_lineage(connection)
        evidence_rows: dict[str, tuple[object, ...]] = {}
        evidence_by_result_uuid: dict[str, str] = {}
        for raw_row in connection.execute(
            """
            SELECT opaque_evidence_sha256, raw_bytes, c3_task_uuid, c3_result_uuid,
                   c3_result_raw_sha256, c3_exporter_commit,
                   c2_canonical_wire_sha256, c2_materialization_id, created_at_ns
            FROM h1_raw_lineage_evidence
            """
        ):
            row = tuple(raw_row)
            opaque_evidence_sha256 = row[0]
            c3_result_uuid = row[3]
            if not isinstance(opaque_evidence_sha256, str) or not isinstance(c3_result_uuid, str):
                raise RegistryConflict("stored H1 evidence identifiers are not text")
            if opaque_evidence_sha256 in evidence_rows:
                raise RegistryConflict("stored H1 opaque evidence identifier is duplicated")
            if c3_result_uuid in evidence_by_result_uuid:
                raise RegistryConflict("stored H1 C3 result identity is duplicated")
            evidence_rows[opaque_evidence_sha256] = row
            evidence_by_result_uuid[c3_result_uuid] = opaque_evidence_sha256
        materializations = tuple(
            connection.execute(
                """
                SELECT lineage_id, opaque_evidence_sha256, data_snapshot_artifact_id,
                       experiment_run_artifact_id, strategy_candidate_artifact_id,
                       strategy_package_artifact_id, replay_artifact_id,
                       paper_artifact_id, decision_artifact_id, c0_data_snapshot_id,
                       c0_experiment_run_id, c0_candidate_id, c0_package_id,
                       c0_trace_id, c0_strategy_family_id, c0_code_sha256,
                       c0_config_sha256, created_at_ns
                FROM h1_lineage_materializations
                """
            )
        )
        materialized_evidence = {row[1] for row in materializations}
        if set(evidence_rows) != materialized_evidence:
            raise RegistryConflict("H1 opaque evidence must have exactly one materialization")

        for row in materializations:
            (
                lineage_id,
                opaque_c3_sha256,
                data_snapshot_artifact_id,
                experiment_run_artifact_id,
                strategy_candidate_artifact_id,
                strategy_package_artifact_id,
                replay_artifact_id,
                paper_artifact_id,
                decision_artifact_id,
                c0_data_snapshot_id,
                c0_experiment_run_id,
                c0_candidate_id,
                c0_package_id,
                c0_trace_id,
                c0_strategy_family_id,
                c0_code_sha256,
                c0_config_sha256,
                recorded_at_ns,
            ) = tuple(row)
            evidence = evidence_rows.get(opaque_c3_sha256)
            if evidence is None:
                raise RegistryConflict("H1 materialization references missing opaque evidence")
            (
                _,
                opaque_c3_bytes,
                c3_task_uuid,
                c3_result_uuid,
                c3_result_raw_sha256,
                c3_exporter_commit,
                c2_canonical_wire_sha256,
                c2_materialization_id,
                evidence_recorded_at_ns,
            ) = tuple(evidence)
            cls._validate_h1_input(
                opaque_c3_bytes=opaque_c3_bytes,
                opaque_c3_sha256=opaque_c3_sha256,
                c3_task_uuid=c3_task_uuid,
                c3_result_uuid=c3_result_uuid,
                c3_result_raw_sha256=c3_result_raw_sha256,
                c3_exporter_commit=c3_exporter_commit,
                c2_canonical_wire_sha256=c2_canonical_wire_sha256,
                c2_materialization_id=c2_materialization_id,
                c0_data_snapshot_id=c0_data_snapshot_id,
                c0_experiment_run_id=c0_experiment_run_id,
                c0_candidate_id=c0_candidate_id,
                c0_package_id=c0_package_id,
                c0_trace_id=c0_trace_id,
                c0_strategy_family_id=c0_strategy_family_id,
                c0_code_sha256=c0_code_sha256,
                c0_config_sha256=c0_config_sha256,
                recorded_at_ns=recorded_at_ns,
            )
            _require_nonnegative_integer(evidence_recorded_at_ns, "stored H1 evidence created_at_ns")
            expected_lineage_id = cls._h1_lineage_identifier(
                opaque_c3_sha256=opaque_c3_sha256,
                c0_data_snapshot_id=c0_data_snapshot_id,
                c0_experiment_run_id=c0_experiment_run_id,
                c0_candidate_id=c0_candidate_id,
                c0_package_id=c0_package_id,
                c0_trace_id=c0_trace_id,
                c0_strategy_family_id=c0_strategy_family_id,
                c0_code_sha256=c0_code_sha256,
                c0_config_sha256=c0_config_sha256,
                c2_materialization_id=c2_materialization_id,
            )
            if lineage_id != expected_lineage_id:
                raise RegistryConflict("stored H1 lineage identifier does not match immutable inputs")
            expected_artifacts = cls._h1_lineage_artifacts(
                lineage_id=lineage_id,
                opaque_c3_sha256=opaque_c3_sha256,
                c3_task_uuid=c3_task_uuid,
                c3_result_uuid=c3_result_uuid,
                c3_result_raw_sha256=c3_result_raw_sha256,
                c3_exporter_commit=c3_exporter_commit,
                c2_canonical_wire_sha256=c2_canonical_wire_sha256,
                c2_materialization_id=c2_materialization_id,
                c0_data_snapshot_id=c0_data_snapshot_id,
                c0_experiment_run_id=c0_experiment_run_id,
                c0_candidate_id=c0_candidate_id,
                c0_package_id=c0_package_id,
                c0_trace_id=c0_trace_id,
                c0_strategy_family_id=c0_strategy_family_id,
                c0_code_sha256=c0_code_sha256,
                c0_config_sha256=c0_config_sha256,
            )
            artifact_ids = (
                data_snapshot_artifact_id,
                experiment_run_artifact_id,
                strategy_candidate_artifact_id,
                strategy_package_artifact_id,
                replay_artifact_id,
                paper_artifact_id,
                decision_artifact_id,
            )
            if tuple(item.artifact_id for item in expected_artifacts) != artifact_ids:
                raise RegistryConflict("stored H1 artifact mapping does not match immutable inputs")
            for artifact in expected_artifacts:
                stored = connection.execute(
                    """
                    SELECT artifact_type, identity_sha256, content_sha256, canonical_payload_json
                    FROM artifacts WHERE artifact_id = ?
                    """,
                    (artifact.artifact_id,),
                ).fetchone()
                if stored is None or tuple(stored) != (
                    artifact.artifact_type,
                    artifact.identity_sha256,
                    artifact.content_sha256,
                    artifact.canonical_payload_json,
                ):
                    raise RegistryConflict("stored H1 artifact is not its canonical source projection")
            placeholders = ", ".join("?" for _ in artifact_ids)
            observed_edges = {
                tuple(edge)
                for edge in connection.execute(
                    f"""
                    SELECT parent_artifact_id, child_artifact_id
                    FROM relations
                    WHERE parent_artifact_id IN ({placeholders})
                       OR child_artifact_id IN ({placeholders})
                    """,
                    (*artifact_ids, *artifact_ids),
                )
            }
            expected_edges = set(zip(artifact_ids, artifact_ids[1:]))
            if observed_edges != expected_edges:
                raise RegistryConflict("stored H1 lineage relations are not one exact adjacent chain")

    @staticmethod
    def _require_matching_data_snapshot_locked(
        connection: sqlite3.Connection,
        data_snapshot_artifact_id: str,
        dataset_sha256: str,
    ) -> None:
        row = connection.execute(
            """
            SELECT artifact_type, content_sha256 FROM artifacts
            WHERE artifact_id = ?
            """,
            (data_snapshot_artifact_id,),
        ).fetchone()
        if row is None or tuple(row) != ("DataSnapshot", dataset_sha256):
            raise RegistryConflict("trial identity requires a matching immutable data snapshot")

    @staticmethod
    def _require_existing_artifact_locked(
        connection: sqlite3.Connection,
        artifact_id: str,
    ) -> None:
        if connection.execute(
            "SELECT 1 FROM artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone() is None:
            raise RegistryConflict("D0 evidence artifact is missing")

    @staticmethod
    def _require_holdout_snapshot_evidence_locked(
        connection: sqlite3.Connection,
        trial_id: str,
        evidence_artifact_id: str,
    ) -> None:
        """A holdout read must name the trial's immutable data snapshot itself."""
        row = connection.execute(
            """
            SELECT data_snapshot_artifact_id
            FROM trial_identities
            WHERE trial_id = ?
            """,
            (trial_id,),
        ).fetchone()
        if row is None or row[0] != evidence_artifact_id:
            raise RegistryConflict("holdout access evidence is not the trial's immutable data snapshot")
        if connection.execute(
            """
            SELECT 1
            FROM trial_stage_transitions
            WHERE trial_id = ?
              AND to_stage IN ('CANDIDATE', 'PROMOTABLE', 'LIVE_CANDIDATE')
            LIMIT 1
            """,
            (trial_id,),
        ).fetchone() is not None:
            raise RegistryConflict("holdout access is forbidden after candidate-or-higher promotion")

    @staticmethod
    def _require_d_migration_locked(connection: sqlite3.Connection) -> None:
        if connection.execute(
            "SELECT 1 FROM schema_migrations WHERE migration_name = ?",
            (_D_MIGRATION,),
        ).fetchone() is None:
            raise RegistryConflict("D overfitting-safety migration is not applied")

    @staticmethod
    def _reject_holdout_for_overfitting_locked(
        connection: sqlite3.Connection,
        trial_id: str,
    ) -> None:
        if connection.execute(
            "SELECT 1 FROM holdout_accesses WHERE trial_id = ? LIMIT 1",
            (trial_id,),
        ).fetchone() is not None:
            raise RegistryConflict("holdout access blocks candidate-or-higher promotion")

    def _require_passed_overfitting_assessment_locked(
        self,
        connection: sqlite3.Connection,
        trial_id: str,
        evidence_artifact_id: str,
    ) -> None:
        """Require a current-count, same-run D proof for a new upper-stage insert."""
        self._require_d_migration_locked(connection)
        self._reject_holdout_for_overfitting_locked(connection, trial_id)
        # A normal SQLite connection cannot insert a D proof (005 requires a
        # registry-local hashing function), but validate again here as defense
        # in depth before a promotion observes any persisted assessment row.
        self._validate_persisted_d(connection)
        identity = connection.execute(
            """
            SELECT strategy_family_id, data_snapshot_artifact_id, dataset_sha256
            FROM trial_identities WHERE trial_id = ?
            """,
            (trial_id,),
        ).fetchone()
        if identity is None:
            raise RegistryConflict("trial identity is missing for overfitting assessment")
        current_trial_count = self._trial_count_locked(connection, *tuple(identity))
        assessment = connection.execute(
            """
            SELECT 1 FROM overfitting_assessments
            WHERE trial_id = ?
              AND evidence_artifact_id = ?
              AND trial_count = ?
              AND passed = 1
            """,
            (trial_id, evidence_artifact_id, current_trial_count),
        ).fetchone()
        if assessment is None:
            raise RegistryConflict(
                "candidate-or-higher stage requires a current passed overfitting assessment"
            )

    @staticmethod
    def _require_trial_bound_stage_evidence_locked(
        connection: sqlite3.Connection,
        trial_id: str,
        evidence_artifact_id: str,
    ) -> None:
        """Require a completed, direct snapshot child with the trial's exact inputs."""
        evidence = connection.execute(
            """
            SELECT 1
            FROM trial_identities AS identity
            JOIN experiments AS experiment
              ON experiment.data_snapshot_artifact_id = identity.data_snapshot_artifact_id
             AND experiment.experiment_run_artifact_id = ?
             AND experiment.code_sha256 = identity.code_sha256
             AND experiment.config_sha256 = identity.config_sha256
            JOIN trials AS source_trial
              ON source_trial.trial_id = experiment.trial_id
             AND source_trial.strategy_family_id = identity.strategy_family_id
            JOIN experiment_registry AS registry
              ON registry.experiment_id = experiment.experiment_id
            JOIN artifacts AS artifact
              ON artifact.artifact_id = ?
             AND artifact.artifact_type = 'ExperimentRun'
            JOIN relations AS relation
              ON relation.parent_artifact_id = identity.data_snapshot_artifact_id
             AND relation.child_artifact_id = ?
             AND relation.relation_type = 'derives_from'
            WHERE identity.trial_id = ?
              AND registry.strategy_family_id = identity.strategy_family_id
              AND registry.dataset_sha256 = identity.dataset_sha256
              AND registry.code_sha256 = identity.code_sha256
              AND registry.config_sha256 = identity.config_sha256
            LIMIT 1
            """,
            (evidence_artifact_id, evidence_artifact_id, evidence_artifact_id, trial_id),
        ).fetchone()
        if evidence is None:
            raise RegistryConflict(
                "trial stage evidence is not a completed immutable run bound to the trial inputs"
            )

    @staticmethod
    def _trial_count_locked(
        connection: sqlite3.Connection,
        strategy_family_id: str,
        data_snapshot_artifact_id: str,
        dataset_sha256: str,
    ) -> int:
        return int(
            connection.execute(
                """
                SELECT COUNT(*) FROM trial_identities
                WHERE strategy_family_id = ?
                  AND data_snapshot_artifact_id = ?
                  AND dataset_sha256 = ?
                """,
                (strategy_family_id, data_snapshot_artifact_id, dataset_sha256),
            ).fetchone()[0]
        )

    @staticmethod
    def _trial_count_at_locked(
        connection: sqlite3.Connection,
        strategy_family_id: str,
        data_snapshot_artifact_id: str,
        dataset_sha256: str,
        recorded_at_ns: int,
    ) -> int:
        """Count only identities already durable at an explicit assessment time."""
        return int(
            connection.execute(
                """
                SELECT COUNT(*) FROM trial_identities
                WHERE strategy_family_id = ?
                  AND data_snapshot_artifact_id = ?
                  AND dataset_sha256 = ?
                  AND created_at_ns <= ?
                """,
                (
                    strategy_family_id,
                    data_snapshot_artifact_id,
                    dataset_sha256,
                    recorded_at_ns,
                ),
            ).fetchone()[0]
        )

    @staticmethod
    def _stage_transition_identifier(
        trial_id: str,
        from_stage: str | None,
        to_stage: str,
        evidence_artifact_id: str,
        recorded_at_ns: int,
    ) -> str:
        return sha256_bytes(
            canonical_bytes(
                {
                    "evidence_artifact_id": evidence_artifact_id,
                    "from_stage": from_stage,
                    "recorded_at_ns": recorded_at_ns,
                    "to_stage": to_stage,
                    "trial_id": trial_id,
                }
            )
        )

    @staticmethod
    def _assessment_identifier(
        trial_id: str,
        evidence_artifact_id: str,
        trial_count: int,
        policy_sha256: str,
        evidence_sha256: str,
        recorded_at_ns: int,
    ) -> str:
        return sha256_bytes(
            canonical_bytes(
                {
                    "evidence_artifact_id": evidence_artifact_id,
                    "evidence_sha256": evidence_sha256,
                    "policy_sha256": policy_sha256,
                    "recorded_at_ns": recorded_at_ns,
                    "trial_count": trial_count,
                    "trial_id": trial_id,
                }
            )
        )

    @staticmethod
    def _current_trial_stage_locked(
        connection: sqlite3.Connection,
        trial_id: str,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT to_stage FROM trial_stage_transitions
            WHERE trial_id = ?
            ORDER BY CASE to_stage
                WHEN 'EXPLORATORY' THEN 1
                WHEN 'CANDIDATE' THEN 2
                WHEN 'PROMOTABLE' THEN 3
                WHEN 'LIVE_CANDIDATE' THEN 4
                ELSE 0
            END DESC
            LIMIT 1
            """,
            (trial_id,),
        ).fetchone()
        return None if row is None else row[0]

    @classmethod
    def _ensure_stage_transition_locked(
        cls,
        connection: sqlite3.Connection,
        *,
        trial_id: str,
        from_stage: str | None,
        to_stage: str,
        evidence_artifact_id: str,
        recorded_at_ns: int,
    ) -> bool:
        identifier = cls._stage_transition_identifier(
            trial_id,
            from_stage,
            to_stage,
            evidence_artifact_id,
            recorded_at_ns,
        )
        existing = connection.execute(
            """
            SELECT stage_transition_id, from_stage, evidence_artifact_id, recorded_at_ns
            FROM trial_stage_transitions
            WHERE trial_id = ? AND to_stage = ?
            """,
            (trial_id, to_stage),
        ).fetchone()
        expected = (identifier, from_stage, evidence_artifact_id, recorded_at_ns)
        if existing is not None:
            if tuple(existing) != expected:
                raise RegistryConflict("trial stage maps to different immutable evidence")
            return False
        connection.execute(
            """
            INSERT INTO trial_stage_transitions (
                stage_transition_id, trial_id, from_stage, to_stage,
                evidence_artifact_id, recorded_at_ns
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                trial_id,
                from_stage,
                to_stage,
                evidence_artifact_id,
                recorded_at_ns,
            ),
        )
        return True

    def _migration_digests(self) -> dict[str, str]:
        return {
            path.name: sha256_bytes(self._read_migration(path))
            for path in self._migration_paths()
        }

    @staticmethod
    def _ensure_migration_ledger(connection: sqlite3.Connection) -> None:
        ledger_exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
        ).fetchone()
        if ledger_exists is None:
            existing = connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type IN ('table', 'index', 'trigger') AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
            if existing:
                raise RegistryConflict("unversioned SQLite schema is not a blank registry")
            connection.execute(
                """
                CREATE TABLE schema_migrations (
                    migration_name TEXT PRIMARY KEY,
                    migration_sha256 TEXT NOT NULL,
                    applied_at_ns INTEGER NOT NULL
                )
                """
            )
            return

        columns = tuple(
            connection.execute("PRAGMA table_info(schema_migrations)").fetchall()
        )
        expected = (
            (0, "migration_name", "TEXT", 0, None, 1),
            (1, "migration_sha256", "TEXT", 1, None, 0),
            (2, "applied_at_ns", "INTEGER", 1, None, 0),
        )
        if tuple(tuple(column) for column in columns) != expected:
            raise RegistryConflict("migration ledger schema is not recognized")

    def _preflight_migration_state(
        self,
        connection: sqlite3.Connection,
        migration_digests: dict[str, str],
    ) -> Optional[str]:
        required_local = {
            _REGISTRY_MIGRATION,
            _LINEAGE_MIGRATION,
            _COMPATIBILITY_MIGRATION,
            _D0_MIGRATION,
            _D_MIGRATION,
            _H1_MIGRATION,
        }
        if not required_local.issubset(migration_digests):
            raise RegistryConflict("required A1/H0, D0, D, and H1 migrations are missing")
        rows = tuple(
            connection.execute(
                "SELECT migration_name, migration_sha256 FROM schema_migrations ORDER BY migration_name"
            ).fetchall()
        )
        if not rows:
            objects = tuple(
                connection.execute(
                    """
                    SELECT type, name FROM sqlite_master
                    WHERE name NOT LIKE 'sqlite_%'
                    ORDER BY type, name
                    """
                ).fetchall()
            )
            if objects != (("table", "schema_migrations"),):
                raise RegistryConflict("empty migration ledger is not a blank registry")
            return None
        ledger = {name: digest for name, digest in rows}
        allowed = required_local
        unexpected = set(ledger) - allowed
        if unexpected:
            raise RegistryConflict("unknown or newer migration marker is applied")
        if set(ledger) == {_REGISTRY_MIGRATION}:
            self._assert_database_integrity(connection)
            base_fingerprint, trigger_fingerprint = self._schema_fingerprints(connection)
            if (
                base_fingerprint != _EXPECTED_A0_BASE_SCHEMA_FINGERPRINT
                or trigger_fingerprint != _EXPECTED_NO_TRIGGER_FINGERPRINT
            ):
                raise RegistryConflict("A0 registry schema fingerprint is not recognized")
            return None
        if (
            set(ledger) - {_REGISTRY_MIGRATION, _LINEAGE_MIGRATION}
            and _COMPATIBILITY_MIGRATION not in ledger
        ):
            raise RegistryConflict("migration ledger order is not recognized")
        if _REGISTRY_MIGRATION not in ledger or _LINEAGE_MIGRATION not in ledger:
            raise RegistryConflict("migration ledger is incomplete")
        if ledger[_REGISTRY_MIGRATION] != migration_digests[_REGISTRY_MIGRATION]:
            raise RegistryConflict("registry migration checksum changed after apply")

        lineage_digest = ledger[_LINEAGE_MIGRATION]
        if lineage_digest == _LEGACY_F36_LINEAGE_SHA256:
            if migration_digests[_LINEAGE_MIGRATION] != _CURRENT_LINEAGE_SHA256:
                raise RegistryConflict("legacy compatibility target does not match the verified 002 migration")
            expected_trigger_fingerprint = (
                _EXPECTED_FINAL_TRIGGER_FINGERPRINT
                if _COMPATIBILITY_MIGRATION in ledger
                else _EXPECTED_F36_TRIGGER_FINGERPRINT
            )
        elif lineage_digest == migration_digests[_LINEAGE_MIGRATION]:
            expected_trigger_fingerprint = _EXPECTED_FINAL_TRIGGER_FINGERPRINT
        else:
            raise RegistryConflict("lineage migration checksum is not a recognized A1/H0 state")

        compatibility_applied = _COMPATIBILITY_MIGRATION in ledger
        d0_applied = _D0_MIGRATION in ledger
        d_applied = _D_MIGRATION in ledger
        h1_applied = _H1_MIGRATION in ledger
        if compatibility_applied:
            if ledger[_COMPATIBILITY_MIGRATION] != migration_digests[_COMPATIBILITY_MIGRATION]:
                raise RegistryConflict("compatibility migration checksum changed after apply")
        elif set(ledger) != {_REGISTRY_MIGRATION, _LINEAGE_MIGRATION}:
            raise RegistryConflict("migration ledger contains an unsupported partial state")
        if d0_applied:
            if not compatibility_applied:
                raise RegistryConflict("D0 migration requires compatibility migration")
            if ledger[_D0_MIGRATION] != migration_digests[_D0_MIGRATION]:
                raise RegistryConflict("D0 migration checksum changed after apply")
        if d_applied:
            if not d0_applied:
                raise RegistryConflict("D migration requires D0 migration")
            if ledger[_D_MIGRATION] != migration_digests[_D_MIGRATION]:
                raise RegistryConflict("D migration checksum changed after apply")
        if h1_applied:
            if not d_applied:
                raise RegistryConflict("H1 migration requires D migration")
            if ledger[_H1_MIGRATION] != migration_digests[_H1_MIGRATION]:
                raise RegistryConflict("H1 migration checksum changed after apply")
            expected_base_fingerprint = _EXPECTED_H1_BASE_SCHEMA_FINGERPRINT
            expected_trigger_fingerprint = _EXPECTED_H1_TRIGGER_FINGERPRINT
        elif d_applied:
            expected_base_fingerprint = _EXPECTED_D_BASE_SCHEMA_FINGERPRINT
            expected_trigger_fingerprint = _EXPECTED_D_TRIGGER_FINGERPRINT
        elif d0_applied:
            expected_base_fingerprint = _EXPECTED_D0_BASE_SCHEMA_FINGERPRINT
            expected_trigger_fingerprint = _EXPECTED_D0_TRIGGER_FINGERPRINT
            if expected_base_fingerprint is None or expected_trigger_fingerprint is None:
                raise RegistryConflict("D0 schema fingerprint is not bound")
        else:
            expected_base_fingerprint = _EXPECTED_BASE_SCHEMA_FINGERPRINT

        self._assert_database_integrity(connection)
        self._assert_schema_fingerprint(
            connection,
            expected_base_fingerprint,
            expected_trigger_fingerprint,
        )
        self._validate_persisted_lineage(connection)
        if d0_applied:
            self._validate_persisted_d0(connection)
        if h1_applied:
            self._validate_persisted_h1(connection)
        return lineage_digest

    @staticmethod
    def _assert_database_integrity(connection: sqlite3.Connection) -> None:
        integrity = tuple(connection.execute("PRAGMA integrity_check").fetchall())
        if integrity != (("ok",),):
            raise RegistryConflict("SQLite integrity check failed before migration")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise RegistryConflict("SQLite foreign-key check failed before migration")

    @staticmethod
    def _assert_schema_fingerprint(
        connection: sqlite3.Connection,
        expected_base_fingerprint: str,
        expected_trigger_fingerprint: str,
    ) -> None:
        base_fingerprint, trigger_fingerprint = ExperimentRegistry._schema_fingerprints(connection)
        if base_fingerprint != expected_base_fingerprint:
            raise RegistryConflict("SQLite table/index schema fingerprint is not recognized")
        if trigger_fingerprint != expected_trigger_fingerprint:
            raise RegistryConflict("SQLite trigger schema fingerprint is not recognized")

    @staticmethod
    def _schema_fingerprints(connection: sqlite3.Connection) -> tuple[str, str]:
        rows = connection.execute(
            """
            SELECT type, name, tbl_name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
        base: list[dict[str, str]] = []
        triggers: list[dict[str, str]] = []
        for object_type, name, table_name, sql in rows:
            if sql is None:
                continue
            entry = {
                "type": object_type,
                "name": name,
                "table": table_name,
                "sql": re.sub(r"\s+", " ", sql.strip()),
            }
            if object_type == "trigger":
                triggers.append(entry)
            else:
                base.append(entry)
        return sha256_bytes(canonical_bytes(base)), sha256_bytes(canonical_bytes(triggers))

    @staticmethod
    def _validate_persisted_lineage(connection: sqlite3.Connection) -> None:
        for result_artifact_id, canonical_summary_json in connection.execute(
            "SELECT result_artifact_id, canonical_summary_json FROM experiment_registry"
        ):
            try:
                summary = json.loads(canonical_summary_json)
            except (TypeError, json.JSONDecodeError) as error:
                raise RegistryConflict("stored experiment summary is not canonical JSON") from error
            if not isinstance(summary, dict) or canonical_bytes(summary).decode("ascii") != canonical_summary_json:
                raise RegistryConflict("stored experiment summary is not canonical JSON")
            if result_artifact_id != sha256_bytes(canonical_summary_json.encode("ascii")):
                raise RegistryConflict("stored experiment summary hash does not match")

        for artifact_id, artifact_type, identity_sha256, content_sha256, payload_json in connection.execute(
            """
            SELECT artifact_id, artifact_type, identity_sha256, content_sha256, canonical_payload_json
            FROM artifacts
            """
        ):
            try:
                payload = json.loads(payload_json)
                artifact = LineageArtifact(
                    artifact_type=artifact_type,
                    identity_sha256=identity_sha256,
                    content_sha256=content_sha256,
                    payload=payload,
                )
            except (TypeError, json.JSONDecodeError, RegistryConflict) as error:
                raise RegistryConflict("stored artifact is not immutable canonical content") from error
            if not isinstance(payload, dict) or artifact.canonical_payload_json != payload_json:
                raise RegistryConflict("stored artifact payload is not canonical JSON")
            if artifact.artifact_id != artifact_id:
                raise RegistryConflict("stored artifact identifier does not match its immutable payload")

        allowed_edges = {
            ("DataSnapshot", "ExperimentRun"),
            ("ExperimentRun", "StrategyCandidate"),
            ("StrategyCandidate", "StrategyPackage"),
            ("StrategyPackage", "Replay"),
            ("Replay", "Paper"),
            ("Paper", "Decision"),
        }
        for parent_type, child_type in connection.execute(
            """
            SELECT parent.artifact_type, child.artifact_type
            FROM relations
            JOIN artifacts AS parent ON parent.artifact_id = relations.parent_artifact_id
            JOIN artifacts AS child ON child.artifact_id = relations.child_artifact_id
            """
        ):
            if (parent_type, child_type) not in allowed_edges:
                raise RegistryConflict("stored lineage relation is not an adjacent canonical edge")

        invalid_experiment = connection.execute(
            """
            SELECT 1
            FROM experiments
            JOIN experiment_registry AS registry
              ON registry.experiment_id = experiments.experiment_id
            JOIN artifacts AS snapshot
              ON snapshot.artifact_id = experiments.data_snapshot_artifact_id
            JOIN artifacts AS run
              ON run.artifact_id = experiments.experiment_run_artifact_id
            WHERE snapshot.artifact_type <> 'DataSnapshot'
               OR run.artifact_type <> 'ExperimentRun'
               OR experiments.result_artifact_id <> registry.result_artifact_id
            LIMIT 1
            """
        ).fetchone()
        if invalid_experiment is not None:
            raise RegistryConflict("stored experiment lineage is not canonical")

    @staticmethod
    def _validate_persisted_d0(connection: sqlite3.Connection) -> None:
        """Bind every persisted D0 row to its canonical, immutable evidence."""
        for (
            trial_id,
            strategy_family_id,
            data_snapshot_artifact_id,
            dataset_sha256,
            code_sha256,
            config_sha256,
            identity_sha256,
        ) in connection.execute(
            """
            SELECT trial_id, strategy_family_id, data_snapshot_artifact_id,
                   dataset_sha256, code_sha256, config_sha256, identity_sha256
            FROM trial_identities
            """
        ):
            _require_sha256(trial_id, "stored trial_id")
            _require_nonempty(strategy_family_id, "stored strategy_family_id")
            _require_sha256(data_snapshot_artifact_id, "stored data_snapshot_artifact_id")
            _require_sha256(dataset_sha256, "stored dataset_sha256")
            _require_sha256(code_sha256, "stored code_sha256")
            _require_sha256(config_sha256, "stored config_sha256")
            _require_sha256(identity_sha256, "stored trial identity_sha256")
            expected_trial_id = sha256_bytes(
                canonical_bytes(
                    {
                        "code_sha256": code_sha256,
                        "config_sha256": config_sha256,
                        "data_snapshot_artifact_id": data_snapshot_artifact_id,
                        "dataset_sha256": dataset_sha256,
                        "strategy_family_id": strategy_family_id,
                    }
                )
            )
            if trial_id != expected_trial_id or identity_sha256 != expected_trial_id:
                raise RegistryConflict("stored trial identity does not match immutable evidence")
            snapshot = connection.execute(
                """
                SELECT artifact_type, content_sha256 FROM artifacts
                WHERE artifact_id = ?
                """,
                (data_snapshot_artifact_id,),
            ).fetchone()
            trial = connection.execute(
                "SELECT strategy_family_id FROM trials WHERE trial_id = ?",
                (trial_id,),
            ).fetchone()
            if (
                snapshot is None
                or tuple(snapshot) != ("DataSnapshot", dataset_sha256)
                or trial is None
                or trial[0] != strategy_family_id
            ):
                raise RegistryConflict("stored trial identity has mismatched parent evidence")
            initial = connection.execute(
                """
                SELECT from_stage, evidence_artifact_id
                FROM trial_stage_transitions
                WHERE trial_id = ? AND to_stage = 'EXPLORATORY'
                """,
                (trial_id,),
            ).fetchone()
            if initial is None or tuple(initial) != (None, data_snapshot_artifact_id):
                raise RegistryConflict("stored trial identity is missing its immutable exploratory stage")

        for holdout_access_id, trial_id, evidence_artifact_id, accessed_at_ns in connection.execute(
            """
            SELECT holdout_access_id, trial_id, evidence_artifact_id, accessed_at_ns
            FROM holdout_accesses
            """
        ):
            _require_sha256(holdout_access_id, "stored holdout_access_id")
            _require_sha256(trial_id, "stored holdout trial_id")
            _require_sha256(evidence_artifact_id, "stored holdout evidence_artifact_id")
            _require_nonnegative_integer(accessed_at_ns, "stored holdout accessed_at_ns")
            expected = sha256_bytes(
                canonical_bytes(
                    {
                        "accessed_at_ns": accessed_at_ns,
                        "evidence_artifact_id": evidence_artifact_id,
                        "trial_id": trial_id,
                    }
                )
            )
            if holdout_access_id != expected:
                raise RegistryConflict("stored holdout access does not match immutable evidence")
            ExperimentRegistry._require_holdout_snapshot_evidence_locked(
                connection,
                trial_id,
                evidence_artifact_id,
            )

        for trial_id in connection.execute(
            "SELECT DISTINCT trial_id FROM trial_stage_transitions"
        ):
            expected_from: str | None = None
            events = connection.execute(
                """
                SELECT stage_transition_id, from_stage, to_stage,
                       evidence_artifact_id, recorded_at_ns
                FROM trial_stage_transitions
                WHERE trial_id = ?
                ORDER BY CASE to_stage
                    WHEN 'EXPLORATORY' THEN 1
                    WHEN 'CANDIDATE' THEN 2
                    WHEN 'PROMOTABLE' THEN 3
                    WHEN 'LIVE_CANDIDATE' THEN 4
                    ELSE 0
                END ASC
                """,
                (trial_id[0],),
            )
            for identifier, from_stage, to_stage, evidence_artifact_id, recorded_at_ns in events:
                if to_stage not in _TRIAL_STAGES or from_stage != expected_from:
                    raise RegistryConflict("stored trial stage transition order is invalid")
                if to_stage == "EXPLORATORY":
                    expected_from = "EXPLORATORY"
                else:
                    if _TRIAL_STAGE_PREDECESSOR.get(to_stage) != from_stage:
                        raise RegistryConflict("stored trial stage transition order is invalid")
                    expected_from = to_stage
                _require_sha256(identifier, "stored stage_transition_id")
                _require_sha256(evidence_artifact_id, "stored stage evidence_artifact_id")
                _require_nonnegative_integer(recorded_at_ns, "stored stage recorded_at_ns")
                expected_identifier = ExperimentRegistry._stage_transition_identifier(
                    trial_id[0],
                    from_stage,
                    to_stage,
                    evidence_artifact_id,
                    recorded_at_ns,
                )
                if identifier != expected_identifier:
                    raise RegistryConflict("stored trial stage does not match immutable evidence")
                if to_stage == "EXPLORATORY":
                    initial = connection.execute(
                        """
                        SELECT data_snapshot_artifact_id FROM trial_identities
                        WHERE trial_id = ?
                        """,
                        (trial_id[0],),
                    ).fetchone()
                    if initial is None or initial[0] != evidence_artifact_id:
                        raise RegistryConflict(
                            "stored exploratory stage is not bound to its immutable data snapshot"
                        )
                else:
                    ExperimentRegistry._require_trial_bound_stage_evidence_locked(
                        connection,
                        trial_id[0],
                        evidence_artifact_id,
                    )

    @staticmethod
    def _validate_persisted_d(connection: sqlite3.Connection) -> None:
        """Recompute every D proof without rewriting historical D0 rows.

        A proof is immutable evidence of the trial count at its own recording
        time.  A later sibling trial deliberately makes it ineligible for a
        *new* promotion, but does not falsify or mutate the original record.
        Likewise, legacy D0 upper stages are preserved as pre-D evidence and
        are not retroactively fabricated into D assessments.
        """
        from .overfitting import OverfittingValidationError, validate_persisted_payload

        for (
            assessment_id,
            trial_id,
            evidence_artifact_id,
            trial_count,
            policy_sha256,
            evidence_json,
            evidence_sha256,
            recorded_at_ns,
            passed,
        ) in connection.execute(
            """
            SELECT assessment_id, trial_id, evidence_artifact_id, trial_count,
                   policy_sha256, canonical_evidence_json, evidence_sha256,
                   recorded_at_ns, passed
            FROM overfitting_assessments
            """
        ):
            _require_sha256(assessment_id, "stored overfitting assessment_id")
            _require_sha256(trial_id, "stored overfitting trial_id")
            _require_sha256(evidence_artifact_id, "stored overfitting evidence_artifact_id")
            _require_nonnegative_integer(trial_count, "stored overfitting trial_count")
            if trial_count < 1:
                raise RegistryConflict("stored overfitting trial_count is invalid")
            _require_sha256(policy_sha256, "stored overfitting policy_sha256")
            _require_sha256(evidence_sha256, "stored overfitting evidence_sha256")
            _require_nonnegative_integer(recorded_at_ns, "stored overfitting recorded_at_ns")
            if passed != 1:
                raise RegistryConflict("stored overfitting assessment is not a passing immutable proof")
            ExperimentRegistry._require_trial_bound_stage_evidence_locked(
                connection,
                trial_id,
                evidence_artifact_id,
            )
            identity = connection.execute(
                """
                SELECT strategy_family_id, data_snapshot_artifact_id, dataset_sha256, created_at_ns
                FROM trial_identities WHERE trial_id = ?
                """,
                (trial_id,),
            ).fetchone()
            if identity is None:
                raise RegistryConflict("stored overfitting assessment trial identity is missing")
            strategy_family_id, data_snapshot_artifact_id, dataset_sha256, created_at_ns = tuple(identity)
            if recorded_at_ns < created_at_ns:
                raise RegistryConflict("stored overfitting assessment predates its trial identity")
            recorded_trial_count = ExperimentRegistry._trial_count_at_locked(
                connection,
                strategy_family_id,
                data_snapshot_artifact_id,
                dataset_sha256,
                recorded_at_ns,
            )
            if recorded_trial_count != trial_count:
                raise RegistryConflict("stored overfitting assessment trial count is not historically bound")
            try:
                payload = json.loads(evidence_json)
                canonical = validate_persisted_payload(payload, trial_count)
            except (TypeError, json.JSONDecodeError, OverfittingValidationError) as error:
                raise RegistryConflict("stored overfitting assessment is not canonical passing evidence") from error
            if canonical_bytes(canonical).decode("ascii") != evidence_json:
                raise RegistryConflict("stored overfitting assessment is not canonical JSON")
            if sha256_bytes(evidence_json.encode("ascii")) != evidence_sha256:
                raise RegistryConflict("stored overfitting assessment hash does not match")
            if canonical["policy_sha256"] != policy_sha256:
                raise RegistryConflict("stored overfitting policy hash does not match")
            expected_assessment_id = ExperimentRegistry._assessment_identifier(
                trial_id,
                evidence_artifact_id,
                trial_count,
                policy_sha256,
                evidence_sha256,
                recorded_at_ns,
            )
            if assessment_id != expected_assessment_id:
                raise RegistryConflict("stored overfitting assessment identifier does not match")

    def _connect(self) -> sqlite3.Connection:
        self._validate_storage_paths()
        connection = sqlite3.connect(
            str(self._database_path),
            timeout=0.0,
            isolation_level=None,
        )
        connection.create_function(
            "research_engine_sha256",
            1,
            _sqlite_canonical_sha256,
            deterministic=True,
        )
        connection.create_function(
            "research_engine_blob_sha256",
            1,
            _sqlite_blob_sha256,
            deterministic=True,
        )
        connection.execute("PRAGMA busy_timeout = 0")
        connection.execute("PRAGMA foreign_keys = ON")
        if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
            connection.close()
            raise RegistryConflict("SQLite foreign-key enforcement could not be enabled")
        return connection

    def _migration_paths(self) -> tuple[Path, ...]:
        paths = tuple(sorted(self._migration_dir.glob("[0-9][0-9][0-9]_*.sql")))
        if not paths:
            raise RegistryConflict("no registry migrations found")
        return paths

    @staticmethod
    def _read_migration(path: Path) -> bytes:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError as error:
            raise RegistryConflict(f"migration is missing: {path.name}") from error
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise RegistryConflict(f"migration must be a regular non-symlink file: {path.name}")
        return path.read_bytes()

    @staticmethod
    def _execute_sql_script(connection: sqlite3.Connection, script: str) -> None:
        """Execute complete SQLite statements without splitting trigger bodies on semicolons."""
        statement = ""
        for character in script:
            statement += character
            if character == ";" and sqlite3.complete_statement(statement):
                if statement.strip():
                    connection.execute(statement)
                statement = ""
        if statement.strip():
            raise RegistryConflict("migration ends with an incomplete SQL statement")

    def _require_disposable_rollback_fixture(self) -> None:
        parent = self._database_path.parent.resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        try:
            parent.relative_to(temporary_root)
        except ValueError as error:
            raise RuntimeBoundaryError(
                "lineage rollback is restricted to a temporary disposable fixture"
            ) from error
        marker = parent / _DISPOSABLE_MARKER
        if not marker.is_file() or marker.read_text(encoding="utf-8") != _DISPOSABLE_MARKER_CONTENT:
            raise RuntimeBoundaryError("disposable lineage rollback marker is missing")

    def _validate_storage_paths(self) -> None:
        """Never follow a symlink or special file at the local SQLite boundary."""
        try:
            parent_mode = self._database_path.parent.lstat().st_mode
        except FileNotFoundError as error:
            raise RuntimeBoundaryError("registry runtime directory is missing") from error
        if stat.S_ISLNK(parent_mode) or not stat.S_ISDIR(parent_mode):
            raise RuntimeBoundaryError("registry runtime directory must be a real directory")
        try:
            database_mode = self._database_path.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(database_mode) or not stat.S_ISREG(database_mode):
            raise RuntimeBoundaryError("registry database must be absent or a regular non-symlink file")

    @staticmethod
    def _rollback(connection: sqlite3.Connection) -> None:
        if connection.in_transaction:
            connection.execute("ROLLBACK")


def _require_sha256(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise RegistryConflict(f"{label} must be a lower-case SHA-256 value")


def _require_git_commit(value: str, label: str) -> None:
    if not isinstance(value, str) or not _GIT_COMMIT_RE.fullmatch(value):
        raise RegistryConflict(f"{label} must be a lower-case full Git commit SHA")


def _require_uuid(value: str, label: str) -> None:
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise RegistryConflict(f"{label} must be a lower-case UUID")


def _require_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise RegistryConflict(f"{label} must be non-empty")


def _require_nonnegative_integer(value: object, label: str) -> None:
    if type(value) is not int or value < 0:
        raise RegistryConflict(f"{label} must be a non-negative integer")


def _sqlite_canonical_sha256(value: object) -> str:
    """Expose only the registry's deterministic SHA-256 primitive to SQLite triggers."""
    if not isinstance(value, str):
        raise ValueError("SQLite canonical hash input must be text")
    return sha256_bytes(value.encode("utf-8"))


def _sqlite_blob_sha256(value: object) -> str:
    """Expose deterministic raw-byte SHA-256 only to the local registry connection."""
    if isinstance(value, memoryview):
        value = value.tobytes()
    if type(value) is not bytes:
        raise ValueError("SQLite BLOB hash input must be bytes")
    return sha256_bytes(value)


def _strict_rfc4648_base64_decode(value: str) -> bytes:
    """Decode padded RFC 4648 Base64 without accepting whitespace or aliases."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    if not value.isascii() or len(value) % 4 != 0:
        raise ValueError("Base64 requires ASCII complete quartets")
    padding = len(value) - len(value.rstrip("="))
    if padding > 2:
        raise ValueError("Base64 padding is not canonical")
    if padding and "=" in value[:-padding]:
        raise ValueError("Base64 padding is not canonical")
    if not padding and "=" in value:
        raise ValueError("Base64 padding is not canonical")
    decoded = bytearray()
    quartet_count = len(value) // 4
    for offset in range(0, len(value), 4):
        quartet = value[offset : offset + 4]
        final = offset // 4 == quartet_count - 1
        pad = quartet.count("=")
        if pad and (not final or quartet[-pad:] != "=" * pad):
            raise ValueError("Base64 padding appears outside the final quartet")
        if pad == 2 and quartet[2:] != "==":
            raise ValueError("Base64 double padding is not canonical")
        if pad == 1 and quartet[3] != "=":
            raise ValueError("Base64 single padding is not canonical")
        values: list[int] = []
        for character in quartet[: 4 - pad]:
            index = alphabet.find(character)
            if index < 0:
                raise ValueError("Base64 contains an invalid character")
            values.append(index)
        if len(values) < 2:
            raise ValueError("Base64 final quartet is incomplete")
        if pad == 2 and values[1] & 0x0F:
            raise ValueError("Base64 double padding carries unused bits")
        if pad == 1 and values[2] & 0x03:
            raise ValueError("Base64 single padding carries unused bits")
        decoded.append((values[0] << 2) | (values[1] >> 4))
        if pad < 2:
            decoded.append(((values[1] & 0x0F) << 4) | (values[2] >> 2))
        if pad == 0:
            decoded.append(((values[2] & 0x03) << 6) | values[3])
    return bytes(decoded)
