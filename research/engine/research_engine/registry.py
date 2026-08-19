"""Single-writer, idempotent SQLite registry for completed A0 experiments."""

from __future__ import annotations

import json
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import RegistryBusy, RegistryConflict, RuntimeBoundaryError
from .hashing import canonical_bytes


@dataclass(frozen=True)
class RegistryRecord:
    """The durable result returned for either a new or replayed experiment."""

    canonical_summary: dict[str, Any]
    result_artifact_id: str
    reused: bool


class ExperimentRegistry:
    """A small SQLite boundary that allows exactly one active writer."""

    def __init__(self, database_path: Path, migration_path: Path) -> None:
        self._database_path = database_path
        self._migration_path = migration_path

    def initialize(self) -> None:
        """Create the local registry under a short immediate-write transaction."""
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._validate_storage_paths()
        migration_sql = self._migration_path.read_text(encoding="utf-8")
        statements = [statement.strip() for statement in migration_sql.split(";") if statement.strip()]
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in statements:
                connection.execute(statement)
            connection.execute("COMMIT")
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry initialization could not acquire the writer lock") from error
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
        """Commit a completed result atomically or return the exact prior result."""
        serialized_summary = canonical_bytes(canonical_summary).decode("utf-8")
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
                connection.execute("COMMIT")
                stored_summary, stored_artifact_id, status = existing
                if status != "completed":
                    raise RegistryConflict("a prior experiment record is not completed")
                if stored_summary != serialized_summary or stored_artifact_id != result_artifact_id:
                    raise RegistryConflict("experiment identity maps to different durable output")
                return RegistryRecord(
                    canonical_summary=json.loads(stored_summary),
                    result_artifact_id=stored_artifact_id,
                    reused=True,
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
            connection.execute("COMMIT")
            return RegistryRecord(
                canonical_summary=canonical_summary,
                result_artifact_id=result_artifact_id,
                reused=False,
            )
        except sqlite3.OperationalError as error:
            self._rollback(connection)
            raise RegistryBusy("registry writer is already held by another process") from error
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        self._validate_storage_paths()
        connection = sqlite3.connect(
            str(self._database_path),
            timeout=0.0,
            isolation_level=None,
        )
        connection.execute("PRAGMA busy_timeout = 0")
        return connection

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
