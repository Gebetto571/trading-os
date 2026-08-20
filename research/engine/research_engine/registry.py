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
from typing import Any, Iterable

from .errors import RegistryBusy, RegistryConflict, RuntimeBoundaryError
from .hashing import canonical_bytes, sha256_bytes


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
_DISPOSABLE_MARKER = ".research-engine-disposable-lineage-fixture"
_DISPOSABLE_MARKER_CONTENT = "research-engine-disposable-lineage-fixture-v1\n"
_LINEAGE_MIGRATION = "002_lineage_foundation.sql"


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
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_name TEXT PRIMARY KEY,
                    migration_sha256 TEXT NOT NULL,
                    applied_at_ns INTEGER NOT NULL
                )
                """
            )
            for migration_path in self._migration_paths():
                name = migration_path.name
                raw = self._read_migration(migration_path)
                digest = sha256_bytes(raw)
                existing = connection.execute(
                    "SELECT migration_sha256 FROM schema_migrations WHERE migration_name = ?",
                    (name,),
                ).fetchone()
                if existing is not None:
                    if existing[0] != digest:
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
            connection.execute("COMMIT")
        except RegistryConflict:
            self._rollback(connection)
            raise
        except UnicodeDecodeError as error:
            self._rollback(connection)
            raise RegistryConflict("migration must be UTF-8 text") from error
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry initialization could not acquire the writer lock") from error
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
            for artifact in artifact_items:
                changed = self._ensure_artifact_locked(connection, artifact, time.time_ns()) or changed
            for parent_artifact_id, child_artifact_id in relation_items:
                changed = (
                    self._ensure_relation_locked(connection, parent_artifact_id, child_artifact_id, time.time_ns())
                    or changed
                )
            connection.execute("COMMIT")
            elapsed = max(1, time.perf_counter_ns() - started)
            return LineageBundleResult(
                artifact_ids=tuple(item.artifact_id for item in artifact_items),
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

    def rollback_lineage_for_disposable_fixture(self) -> None:
        """Reverse only the A1/H0 migration in a marked temporary test fixture."""
        self._require_disposable_rollback_fixture()
        rollback_path = self._migration_dir / "rollback" / _LINEAGE_MIGRATION
        raw = self._read_migration(rollback_path)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
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
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry rollback could not acquire the writer lock") from error
        except sqlite3.Error as error:
            self._rollback(connection)
            raise RegistryConflict("lineage rollback failed closed") from error
        finally:
            connection.close()

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
        self._ensure_artifact_locked(connection, snapshot, created_at_ns)
        self._ensure_artifact_locked(connection, experiment_run, created_at_ns)
        self._ensure_relation_locked(connection, snapshot.artifact_id, experiment_run.artifact_id, created_at_ns)
        self._ensure_trial_locked(connection, trial_id, strategy_family_id, created_at_ns)
        self._ensure_experiment_locked(
            connection,
            experiment_id=experiment_id,
            trial_id=trial_id,
            data_snapshot_artifact_id=snapshot.artifact_id,
            experiment_run_artifact_id=experiment_run.artifact_id,
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
    ) -> bool:
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
            return False

        natural = connection.execute(
            """
            SELECT artifact_id, content_sha256, canonical_payload_json
            FROM artifacts WHERE artifact_type = ? AND identity_sha256 = ?
            """,
            (artifact.artifact_type, artifact.identity_sha256),
        ).fetchone()
        if natural is not None:
            if natural[0] != artifact.artifact_id or natural[1] != artifact.content_sha256 or natural[2] != artifact.canonical_payload_json:
                raise RegistryConflict("artifact identity maps to different immutable content")
            return False

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
        return True

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

    def _connect(self) -> sqlite3.Connection:
        self._validate_storage_paths()
        connection = sqlite3.connect(
            str(self._database_path),
            timeout=0.0,
            isolation_level=None,
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


def _require_nonempty(value: str, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise RegistryConflict(f"{label} must be non-empty")
