from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from .validation import canonical_bytes, sha256_bytes


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class IntegrityConflict(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


class OwnershipConflict(ValueError):
    pass


class DisposableMigrationRequired(ValueError):
    pass


class NotReversibleMigration(ValueError):
    pass


CHIEF_ENGINEER_PRINCIPAL = "chief-engineer"
READ_ONLY_OPERATIONAL_ROOT = "var/outbox"


DISPOSABLE_MARKER = ".trading-os-disposable-fixture"
DISPOSABLE_MARKER_CONTENT = "trading-os-disposable-fixture-v1\n"
REVERSIBLE_DOWN_SQL = {
    4: """
DROP INDEX IF EXISTS idx_messages_active_writer;
DROP INDEX IF EXISTS idx_messages_chief_engineer_claimable;
ALTER TABLE messages DROP COLUMN result_message_id;
ALTER TABLE messages DROP COLUMN verification_verdict;
ALTER TABLE messages DROP COLUMN owned_paths_json;
ALTER TABLE messages DROP COLUMN active_writer;
ALTER TABLE messages DROP COLUMN approval_state;
ALTER TABLE messages DROP COLUMN authority;
ALTER TABLE messages DROP COLUMN local_lane;
ALTER TABLE messages DROP COLUMN cloud_conversation_key;
ALTER TABLE messages DROP COLUMN project_domain;
ALTER TABLE messages DROP COLUMN base_commit;
ALTER TABLE messages DROP COLUMN updated_by;
ALTER TABLE messages DROP COLUMN revision;
""",
}


TRANSITIONS = {
    "queued": {"processing", "failed"},
    # received -> processing yalnız atomik claim_message() üzerinden yapılır.
    "received": {"failed"},
    "processing": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


class Store:
    def __init__(self, database: Path, migrations: Path) -> None:
        self.database = database
        self.migrations = migrations

    def _secure_database_files(self) -> None:
        for path in (self.database, Path(str(self.database) + "-wal"), Path(str(self.database) + "-shm")):
            if path.exists():
                os.chmod(path, 0o600)

    def connect(self, timeout: float = 5.0) -> sqlite3.Connection:
        parent_existed = self.database.parent.exists()
        self.database.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not parent_existed:
            os.chmod(self.database.parent, 0o700)
        connection = sqlite3.connect(self.database, timeout=timeout)
        self._secure_database_files()
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def migrate(self) -> int:
        applied = 0
        try:
            with self.connect() as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
                )
                known = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
                for path in sorted(self.migrations.glob("[0-9][0-9][0-9]_*.sql")):
                    version = int(path.name.split("_", 1)[0])
                    if version in known:
                        continue
                    sql = path.read_text(encoding="utf-8")
                    statements = sql.splitlines()
                    body_lines = []
                    for line in statements:
                        if line.strip().upper().startswith("PRAGMA "):
                            connection.execute(line.strip().rstrip(";"))
                        else:
                            body_lines.append(line)
                    applied_at = utc_now().replace("'", "''")
                    script = (
                        "BEGIN IMMEDIATE;\n" + "\n".join(body_lines) +
                        f"\nINSERT INTO schema_migrations(version, applied_at) VALUES ({version}, '{applied_at}');\nCOMMIT;"
                    )
                    try:
                        connection.executescript(script)
                    except Exception:
                        if connection.in_transaction:
                            connection.rollback()
                        raise
                    applied += 1
        finally:
            self._secure_database_files()
        return applied

    def _require_disposable_migration_fixture(self) -> None:
        parent = self.database.parent.resolve()
        temporary_root = Path(tempfile.gettempdir()).resolve()
        try:
            parent.relative_to(temporary_root)
        except ValueError as error:
            raise DisposableMigrationRequired("Down-migration yalnız geçici disposable fixture altında çalışabilir") from error
        marker = parent / DISPOSABLE_MARKER
        if not marker.is_file() or marker.read_text(encoding="utf-8") != DISPOSABLE_MARKER_CONTENT:
            raise DisposableMigrationRequired("Disposable fixture marker doğrulanamadı")

    def migrate_down_disposable(self, target_version: int) -> int:
        """Revert only explicitly declared migrations in a marked temporary fixture."""
        if isinstance(target_version, bool) or not isinstance(target_version, int) or target_version < 0:
            raise ValueError("Hedef migration sürümü geçerli bir tam sayı olmalı")
        self._require_disposable_migration_fixture()
        reverted = 0
        try:
            with self.connect() as connection:
                known = [row[0] for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version DESC"
                )]
                if not known:
                    raise NotReversibleMigration("Uygulanmış migration yok")
                current_version = known[0]
                if target_version >= current_version:
                    raise ValueError("Hedef sürüm mevcut sürümden küçük olmalı")
                versions = list(range(current_version, target_version, -1))
                unsupported = [version for version in versions if version not in REVERSIBLE_DOWN_SQL]
                if unsupported:
                    raise NotReversibleMigration(
                        f"Açık down SQL tanımı yok: {', '.join(map(str, unsupported))}"
                    )
                script = "BEGIN IMMEDIATE;\n"
                for version in versions:
                    script += REVERSIBLE_DOWN_SQL[version]
                    script += f"DELETE FROM schema_migrations WHERE version = {version};\n"
                script += "COMMIT;"
                try:
                    connection.executescript(script)
                except Exception:
                    if connection.in_transaction:
                        connection.rollback()
                    raise
                reverted = len(versions)
        finally:
            self._secure_database_files()
        return reverted

    def put_message(
        self, message: dict, direction: str, status: str, source_uri: str | None = None,
        raw_payload: bytes | None = None,
    ) -> bool:
        now = utc_now()
        canonical = canonical_bytes(message)
        payload_sha = sha256_bytes(canonical)
        raw_sha = sha256_bytes(raw_payload if raw_payload is not None else canonical)
        metadata = message["metadata"]
        result = metadata.get("result", {}) if isinstance(metadata, dict) else {}
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT payload_sha256, payload_json FROM messages WHERE id = ?", (message["id"],)
            ).fetchone()
            if existing is not None:
                existing_sha = existing["payload_sha256"] or sha256_bytes(
                    canonical_bytes(json.loads(existing["payload_json"]))
                )
                if existing_sha != payload_sha:
                    raise IntegrityConflict(f"Aynı UUID farklı içerikle kullanılmış: {message['id']}")
                return False
            connection.execute(
                """
                INSERT INTO messages (
                    id, schema_version, created_at, received_at, sender, recipient,
                    message_type, subject, body, correlation_id, direction, status,
                    source_uri, payload_json, payload_sha256, raw_sha256, updated_at,
                    updated_by, project_domain, cloud_conversation_key, local_lane,
                    authority, approval_state, verification_verdict
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["id"], message["schema_version"], message["created_at"],
                    now if direction == "inbound" else None, message["sender"], message["recipient"],
                    message["type"], message["subject"], message["body"], message["correlation_id"],
                    direction, status, source_uri,
                    json.dumps(message, ensure_ascii=False, sort_keys=True), payload_sha, raw_sha, now,
                    message["sender"], metadata.get("project_domain"),
                    metadata.get("cloud_conversation_key"), metadata.get("local_lane"),
                    metadata.get("authority"), metadata.get("approval_state"),
                    result.get("verification_verdict"),
                ),
            )
            for artifact in message["artifacts"]:
                connection.execute(
                    "INSERT INTO artifacts(message_id, name, uri, sha256, media_type, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        message["id"], artifact["name"], artifact.get("uri", artifact.get("url")),
                        artifact.get("sha256"), artifact.get("kind"), now,
                    ),
                )
            return True

    def list_messages(self, limit: int = 25) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute(
                "SELECT id, created_at, sender, recipient, message_type, status, subject FROM messages ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ))

    def update_status(
        self, message_id: str, status: str, error: str | None = None, worker: str | None = None,
    ) -> bool:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
            if row is None:
                return False
            current = row["status"]
            if current == "processing" and status in {"completed", "failed"}:
                if not worker:
                    raise InvalidTransition("Terminal durum için claim sahibi worker zorunlu")
                if (
                    status == "completed"
                    and row["authority"] == CHIEF_ENGINEER_PRINCIPAL
                    and row["active_writer"] == CHIEF_ENGINEER_PRINCIPAL
                ):
                    if row["result_message_id"] is None:
                        raise InvalidTransition("Chief görevi bağlı immutable sonuç olmadan tamamlanamaz")
                    result = connection.execute(
                        "SELECT * FROM messages WHERE id=?", (row["result_message_id"],)
                    ).fetchone()
                    if result is None or not self._chief_result_matches_task(row, result):
                        raise InvalidTransition("Chief görevinin bağlı sonucu rota veya bütünlükle eşleşmedi")
                now = utc_now()
                cursor = connection.execute(
                    """UPDATE messages SET status=?, last_error=?, terminal_by=?, terminal_at=?, lease_until=NULL,
                       revision=revision+1, updated_by=?, updated_at=?
                       WHERE id=? AND status='processing' AND claimed_by=?
                       AND lease_until IS NOT NULL AND lease_until > ?""",
                    (status, error, worker, now, worker, now, message_id, worker, now),
                )
                if cursor.rowcount != 1:
                    raise InvalidTransition("Claim sahibi veya geçerli lease eşleşmedi")
                return True
            if status == current:
                if status in {"completed", "failed"}:
                    raise InvalidTransition("Terminal durum yeniden yazılamaz")
                return True
            if status == "processing" and row["direction"] == "inbound":
                raise InvalidTransition("Inbound processing yalnız claim_message ile başlatılabilir")
            if status not in TRANSITIONS.get(current, set()):
                raise InvalidTransition(f"İzin verilmeyen durum geçişi: {current} -> {status}")
            connection.execute(
                """UPDATE messages SET status = ?, last_error = ?, revision=revision+1,
                   updated_by = COALESCE(?, updated_by),
                   claimed_by = CASE WHEN ? IN ('completed','failed') THEN NULL ELSE claimed_by END,
                   lease_until = CASE WHEN ? IN ('completed','failed') THEN NULL ELSE lease_until END,
                   updated_at = ? WHERE id = ?""",
                (status, error, worker, status, status, utc_now(), message_id),
            )
            return True

    def activate_inbound(self, message_id: str, archive_uri: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE messages SET status='received', source_uri=?, received_at=?, updated_at=?
                   WHERE id=? AND direction='inbound' AND status='queued'""",
                (archive_uri, utc_now(), utc_now(), message_id),
            )
            return cursor.rowcount == 1

    def cancel_inbound_reservation(self, message_id: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM messages WHERE id=? AND direction='inbound' AND status='queued'",
                (message_id,),
            )
            return cursor.rowcount == 1

    def reconcile_pending_ingests(self) -> int:
        recovered = 0
        with self.connect() as connection:
            rows = list(connection.execute(
                "SELECT id, source_uri FROM messages WHERE direction='inbound' AND status='queued'"
            ))
            for row in rows:
                uri = urlparse(row["source_uri"] or "")
                if uri.scheme == "file" and Path(unquote(uri.path)).is_file():
                    cursor = connection.execute(
                        "UPDATE messages SET status='received', received_at=?, updated_at=? WHERE id=? AND status='queued'",
                        (utc_now(), utc_now(), row["id"]),
                    )
                    recovered += cursor.rowcount
        return recovered

    def claim_message(self, worker: str, lease_seconds: int = 300) -> sqlite3.Row | None:
        if not worker or lease_seconds < 1:
            raise ValueError("worker ve pozitif lease_seconds gerekli")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id FROM messages
                   WHERE direction = 'inbound' AND status = 'received'
                     AND COALESCE(authority, '') <> 'chief-engineer'
                     AND (lease_until IS NULL OR lease_until <= ?)
                   ORDER BY created_at, id LIMIT 1""", (now,),
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """UPDATE messages SET status='processing', claimed_by=?, claimed_at=?, lease_until=?,
                   attempt_count=attempt_count+1, updated_at=? WHERE id=? AND status='received'""",
                (worker, now, lease, now, row["id"]),
            )
            return connection.execute("SELECT * FROM messages WHERE id=?", (row["id"],)).fetchone()

    @staticmethod
    def _normalize_owned_paths(paths: list[str]) -> list[str]:
        if not isinstance(paths, list):
            raise ValueError("owned_paths JSON listesi olmalı")
        if not paths:
            raise ValueError("En az bir owned_path gerekli")
        normalized: list[str] = []
        for raw in paths:
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError("owned_path boş olamaz")
            candidate = PurePosixPath(raw.strip().replace("\\", "/"))
            if candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
                raise ValueError(f"owned_path repository göreli ve normalleştirilmiş olmalı: {raw}")
            value = candidate.as_posix().rstrip("/")
            if not value:
                raise ValueError("owned_path repository kökü olamaz")
            normalized.append(value)
        result = sorted(set(normalized))
        for index, left in enumerate(result):
            for right in result[index + 1:]:
                if right.startswith(left + "/"):
                    raise ValueError(f"owned_paths kendi içinde örtüşüyor: {left} ve {right}")
        return result

    @staticmethod
    def _paths_overlap(left: list[str], right: list[str]) -> bool:
        return any(
            a == b or a.startswith(b + "/") or b.startswith(a + "/")
            for a in left for b in right
        )

    @staticmethod
    def _is_read_only_operational_scope(paths: list[str]) -> bool:
        """Only result-outbox paths may coexist with a mutating Chief task."""
        return bool(paths) and all(
            path == READ_ONLY_OPERATIONAL_ROOT or path.startswith(READ_ONLY_OPERATIONAL_ROOT + "/")
            for path in paths
        )

    @classmethod
    def _is_mutating_chief_scope(cls, paths: list[str]) -> bool:
        return not cls._is_read_only_operational_scope(paths)

    @staticmethod
    def _require_canonical_uuid(task_id: str) -> None:
        if not isinstance(task_id, str):
            raise ValueError("Görev UUID metin olmalı")
        try:
            canonical = str(uuid.UUID(task_id))
        except (AttributeError, ValueError) as error:
            raise ValueError("Görev UUID geçersiz") from error
        if canonical != task_id:
            raise ValueError("Görev UUID canonical küçük-harf biçiminde olmalı")

    def _stored_owned_paths(self, row: sqlite3.Row) -> list[str]:
        try:
            raw_paths = json.loads(row["owned_paths_json"] or "[]")
            if not isinstance(raw_paths, list):
                return []
            return self._normalize_owned_paths(raw_paths)
        except (TypeError, ValueError, json.JSONDecodeError):
            # An unreadable active ownership record is never considered read-only.
            return []

    def _frozen_owned_paths(self, row: sqlite3.Row) -> list[str] | None:
        try:
            payload = json.loads(row["payload_json"])
            metadata = payload["metadata"]
        except (KeyError, TypeError, json.JSONDecodeError) as error:
            raise InvalidTransition("Chief task payload binding okunamadı") from error
        frozen_paths = metadata.get("FROZEN_OWNED_PATHS")
        if frozen_paths is None:
            return None
        try:
            return self._normalize_owned_paths(frozen_paths)
        except (TypeError, ValueError) as error:
            raise InvalidTransition("Frozen owned path binding geçersiz") from error

    def _assert_mutating_chief_writer_available(
        self, connection: sqlite3.Connection, candidate_id: str, candidate_paths: list[str],
    ) -> None:
        active = connection.execute(
            """SELECT id, owned_paths_json FROM messages
               WHERE direction='inbound' AND status='processing'
                 AND active_writer=? AND id<>?""",
            (CHIEF_ENGINEER_PRINCIPAL, candidate_id),
        )
        for item in active:
            other_paths = self._stored_owned_paths(item)
            if self._paths_overlap(candidate_paths, other_paths):
                raise OwnershipConflict(
                    f"Dosya sahipliği çakışıyor: {candidate_id} ile aktif {item['id']}"
                )
            if (
                self._is_mutating_chief_scope(candidate_paths)
                and self._is_mutating_chief_scope(other_paths)
            ):
                raise OwnershipConflict(
                    f"Başka mutating Chief görevi aktif: {item['id']}"
                )

    def _require_exact_chief_binding(
        self,
        row: sqlite3.Row,
        task_id: str,
        lane: str,
        principal: str,
        base_commit: str,
        paths: list[str],
    ) -> None:
        self._require_canonical_uuid(task_id)
        if principal != CHIEF_ENGINEER_PRINCIPAL:
            raise InvalidTransition("Exact Chief claim yalnız chief-engineer principal ile yapılabilir")
        if row["id"] != task_id:
            raise InvalidTransition("Exact Chief claim hedef UUID ile eşleşmedi")
        if (
            row["direction"] != "inbound"
            or row["message_type"] != "task"
            or row["authority"] != CHIEF_ENGINEER_PRINCIPAL
            or row["approval_state"] != "approved_for_local_implementation"
            or row["local_lane"] != lane
        ):
            raise InvalidTransition("Exact Chief claim görev kimliği veya lane ile eşleşmedi")
        try:
            payload = json.loads(row["payload_json"])
            metadata = payload["metadata"]
            manifest = metadata["SCOPE_BINDING_MANIFEST"]
            frozen_paths = self._normalize_owned_paths(metadata["FROZEN_OWNED_PATHS"])
            exact_paths = self._normalize_owned_paths(manifest["exact_owned_paths"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise InvalidTransition("Exact Chief claim için frozen scope binding doğrulanamadı") from error
        if payload.get("id") != task_id:
            raise InvalidTransition("Görev payload UUID'si kayıt UUID'siyle eşleşmedi")
        if manifest.get("active_writer_principal") != principal:
            raise InvalidTransition("Frozen principal binding eşleşmedi")
        if manifest.get("canonical_lane") != lane:
            raise InvalidTransition("Frozen lane binding eşleşmedi")
        if manifest.get("expected_base_commit") != base_commit:
            raise InvalidTransition("Frozen implementation base eşleşmedi")
        if frozen_paths != paths or exact_paths != paths:
            raise InvalidTransition("Frozen owned path binding eşleşmedi")
        if row["base_commit"] not in (None, base_commit):
            raise InvalidTransition("Mevcut implementation base frozen binding ile eşleşmedi")
        stored_paths = self._stored_owned_paths(row)
        if stored_paths and stored_paths != paths:
            raise InvalidTransition("Mevcut owned path frozen binding ile eşleşmedi")
        if row["active_writer"] not in (None, principal):
            raise InvalidTransition("Mevcut active writer frozen principal ile eşleşmedi")

    @staticmethod
    def _lease_window(lease_seconds: int) -> tuple[str, str]:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")
        return now, lease

    def claim_chief_engineer_task(
        self, lane: str, base_commit: str, owned_paths: list[str], lease_seconds: int = 300,
    ) -> sqlite3.Row | None:
        if not lane or not base_commit or lease_seconds < 1:
            raise ValueError("lane, base_commit ve pozitif lease_seconds gerekli")
        paths = self._normalize_owned_paths(owned_paths)
        now, lease = self._lease_window(lease_seconds)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT * FROM messages
                   WHERE direction='inbound' AND status='received' AND message_type='task'
                     AND authority='chief-engineer'
                     AND approval_state='approved_for_local_implementation'
                     AND local_lane=? AND result_message_id IS NULL
                   ORDER BY created_at, id LIMIT 1""",
                (lane,),
            ).fetchone()
            if row is None:
                return None
            frozen_paths = self._frozen_owned_paths(row)
            if frozen_paths is not None:
                raise InvalidTransition("Frozen Chief görevleri yalnız UUID-hedefli claim ile alınabilir")
            self._assert_mutating_chief_writer_available(connection, row["id"], paths)
            cursor = connection.execute(
                """UPDATE messages SET status='processing', claimed_by='chief-engineer',
                   claimed_at=?, lease_until=?, attempt_count=attempt_count+1,
                   revision=revision+1, updated_by='chief-engineer', base_commit=?,
                   active_writer='chief-engineer', owned_paths_json=?, updated_at=?
                   WHERE id=? AND status='received' AND authority='chief-engineer'
                     AND approval_state='approved_for_local_implementation' AND local_lane=?""",
                (now, lease, base_commit, json.dumps(paths), now, row["id"], lane),
            )
            if cursor.rowcount != 1:
                raise InvalidTransition("Chief Engineer görevi atomik olarak sahiplenilemedi")
            return connection.execute("SELECT * FROM messages WHERE id=?", (row["id"],)).fetchone()

    def claim_chief_engineer_task_by_id(
        self,
        task_id: str,
        lane: str,
        base_commit: str,
        owned_paths: list[str],
        lease_seconds: int = 300,
        principal: str = CHIEF_ENGINEER_PRINCIPAL,
    ) -> sqlite3.Row | None:
        if not lane or not base_commit or lease_seconds < 1:
            raise ValueError("lane, base_commit ve pozitif lease_seconds gerekli")
        self._require_canonical_uuid(task_id)
        paths = self._normalize_owned_paths(owned_paths)
        now, lease = self._lease_window(lease_seconds)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM messages WHERE id=?", (task_id,)).fetchone()
            if row is None:
                return None
            self._require_exact_chief_binding(row, task_id, lane, principal, base_commit, paths)
            if row["status"] != "received":
                raise InvalidTransition(f"Exact Chief claim için görev received değil: {row['status']}")
            if row["result_message_id"] is not None:
                raise InvalidTransition("Sonuç bağlı görev yeniden claim edilemez")
            self._assert_mutating_chief_writer_available(connection, task_id, paths)
            cursor = connection.execute(
                """UPDATE messages SET status='processing', claimed_by=?, claimed_at=?, lease_until=?,
                   attempt_count=attempt_count+1, revision=revision+1, updated_by=?, base_commit=?,
                   active_writer=?, owned_paths_json=?, updated_at=?
                   WHERE id=? AND revision=? AND status='received' AND direction='inbound'
                     AND message_type='task' AND authority=?
                     AND approval_state='approved_for_local_implementation' AND local_lane=?
                     AND result_message_id IS NULL""",
                (
                    principal, now, lease, principal, base_commit, principal, json.dumps(paths), now,
                    task_id, row["revision"], CHIEF_ENGINEER_PRINCIPAL, lane,
                ),
            )
            if cursor.rowcount != 1:
                raise InvalidTransition("Exact Chief claim CAS koşulunu kaybetti")
            return connection.execute("SELECT * FROM messages WHERE id=?", (task_id,)).fetchone()

    def reclaim_chief_engineer_task_by_id(
        self,
        task_id: str,
        lane: str,
        lease_seconds: int = 300,
        principal: str = CHIEF_ENGINEER_PRINCIPAL,
    ) -> sqlite3.Row | None:
        if not lane or lease_seconds < 1:
            raise ValueError("lane ve pozitif lease_seconds gerekli")
        self._require_canonical_uuid(task_id)
        now, lease = self._lease_window(lease_seconds)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM messages WHERE id=?", (task_id,)).fetchone()
            if row is None:
                return None
            paths = self._stored_owned_paths(row)
            if not row["base_commit"] or not paths:
                raise InvalidTransition("Exact reclaim için mevcut base veya owned path bulunamadı")
            self._require_exact_chief_binding(
                row, task_id, lane, principal, row["base_commit"], paths,
            )
            if row["status"] != "processing":
                raise InvalidTransition(f"Exact Chief reclaim için görev processing değil: {row['status']}")
            if row["claimed_by"] != principal or row["active_writer"] != principal:
                raise InvalidTransition("Exact Chief reclaim sahibi eşleşmedi")
            if row["result_message_id"] is not None:
                raise InvalidTransition("Sonuç bağlı görev reclaim edilemez")
            if row["lease_until"] is None or row["lease_until"] > now:
                raise InvalidTransition("Exact Chief reclaim için lease süresi dolmamış")
            self._assert_mutating_chief_writer_available(connection, task_id, paths)
            cursor = connection.execute(
                """UPDATE messages SET claimed_at=?, lease_until=?, attempt_count=attempt_count+1,
                   revision=revision+1, updated_by=?, updated_at=?
                   WHERE id=? AND revision=? AND status='processing' AND claimed_by=?
                     AND active_writer=? AND lease_until IS NOT NULL AND lease_until<=?
                     AND result_message_id IS NULL""",
                (
                    now, lease, principal, now, task_id, row["revision"], principal,
                    principal, now,
                ),
            )
            if cursor.rowcount != 1:
                raise InvalidTransition("Exact Chief reclaim CAS koşulunu kaybetti")
            return connection.execute("SELECT * FROM messages WHERE id=?", (task_id,)).fetchone()

    def has_active_chief_lease(self, task_id: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM messages WHERE id=? AND direction='inbound' AND status='processing'
                   AND claimed_by=? AND active_writer=? AND lease_until IS NOT NULL AND lease_until>?""",
                (task_id, CHIEF_ENGINEER_PRINCIPAL, CHIEF_ENGINEER_PRINCIPAL, now),
            ).fetchone()
            return row is not None

    def _chief_result_matches_task(self, task: sqlite3.Row, result: sqlite3.Row) -> bool:
        expected_correlation = task["correlation_id"] or task["id"]
        if (
            result["direction"] != "outbound"
            or result["message_type"] != "response"
            or result["correlation_id"] != expected_correlation
        ):
            return False
        try:
            task_payload = json.loads(task["payload_json"])
            result_payload = json.loads(result["payload_json"])
            task_metadata = task_payload["metadata"]
            result_metadata = result_payload["metadata"]
            result_paths = self._normalize_owned_paths(result_metadata["owned_paths"])
            task_paths = self._stored_owned_paths(task)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return False
        return (
            result_payload.get("sender") == "codex-local"
            and result_payload.get("recipient") == "chatgpt"
            and result_metadata.get("authority") == CHIEF_ENGINEER_PRINCIPAL
            and result_metadata.get("approval_state") == "implemented_locally"
            and result_metadata.get("project_domain") == task_metadata.get("project_domain")
            and result_metadata.get("cloud_conversation_key") == task_metadata.get("cloud_conversation_key")
            and result_metadata.get("local_lane") == task_metadata.get("local_lane")
            and result_metadata.get("base_commit") == task["base_commit"]
            and result_metadata.get("active_writer") == task["active_writer"]
            and result_paths == task_paths
        )

    def link_result(self, task_id: str, result_id: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            task = connection.execute("SELECT * FROM messages WHERE id=?", (task_id,)).fetchone()
            result = connection.execute("SELECT * FROM messages WHERE id=?", (result_id,)).fetchone()
            if task is None or result is None:
                return False
            if not self._chief_result_matches_task(task, result):
                return False
            cursor = connection.execute(
                """UPDATE messages SET result_message_id=?, revision=revision+1,
                   updated_by='chief-engineer', updated_at=?
                   WHERE id=? AND direction='inbound' AND status='processing'
                     AND claimed_by=? AND active_writer=? AND lease_until IS NOT NULL
                     AND lease_until>? AND result_message_id IS NULL""",
                (result_id, now, task_id, CHIEF_ENGINEER_PRINCIPAL, CHIEF_ENGINEER_PRINCIPAL, now),
            )
            return cursor.rowcount == 1

    def discard_unlinked_outbound_result(self, result_id: str, source_uri: str) -> bool:
        """Compensate only a just-created local result that could not be linked to a task."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM messages WHERE id=?", (result_id,)).fetchone()
            if (
                row is None
                or row["direction"] != "outbound"
                or row["message_type"] != "response"
                or row["status"] != "queued"
                or row["source_uri"] != source_uri
            ):
                return False
            linked = connection.execute(
                "SELECT 1 FROM messages WHERE result_message_id=? LIMIT 1", (result_id,)
            ).fetchone()
            if linked is not None:
                return False
            connection.execute("DELETE FROM artifacts WHERE message_id=?", (result_id,))
            cursor = connection.execute("DELETE FROM messages WHERE id=?", (result_id,))
            return cursor.rowcount == 1

    def recover_expired(self, reason: str = "lease expired") -> int:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = list(connection.execute(
                """SELECT * FROM messages WHERE status='processing'
                   AND lease_until IS NOT NULL AND lease_until <= ?""",
                (now,),
            ))
            recovered = 0
            for row in rows:
                if row["authority"] == CHIEF_ENGINEER_PRINCIPAL:
                    try:
                        frozen_paths = self._frozen_owned_paths(row)
                    except InvalidTransition:
                        continue
                    if frozen_paths is not None:
                        continue
                cursor = connection.execute(
                    """UPDATE messages SET status='received', claimed_by=NULL, claimed_at=NULL,
                       lease_until=NULL, revision=revision+1, updated_by='recovery', last_error=?, updated_at=?
                       WHERE id=? AND status='processing' AND lease_until IS NOT NULL AND lease_until <= ?""",
                    (reason, now, row["id"], now),
                )
                recovered += cursor.rowcount
            return recovered

    def recover_message(self, message_id: str, reason: str = "manual recovery") -> bool:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
            if row is None:
                return False
            if row["direction"] != "inbound":
                raise InvalidTransition("Yalnız inbound mesaj sahipliği kurtarılabilir")
            if row["authority"] == CHIEF_ENGINEER_PRINCIPAL:
                try:
                    frozen_paths = self._frozen_owned_paths(row)
                except InvalidTransition as error:
                    raise InvalidTransition("Chief task frozen binding okunamadı; generic recovery reddedildi") from error
                if frozen_paths is not None:
                    raise InvalidTransition("Frozen Chief görevleri yalnız exact UUID reclaim ile kurtarılabilir")
            recoverable = row["status"] == "failed" or (
                row["status"] == "processing" and row["lease_until"] is not None and row["lease_until"] <= now
            )
            if not recoverable:
                raise InvalidTransition(f"Mesaj kurtarılabilir durumda değil: {row['status']}")
            connection.execute(
                """UPDATE messages SET status='received', claimed_by=NULL, claimed_at=NULL,
                   lease_until=NULL, terminal_by=NULL, terminal_at=NULL,
                   revision=revision+1, updated_by='recovery', last_error=?, updated_at=? WHERE id=?""",
                (reason, now, message_id),
            )
            return True

    def record_quarantine(
        self, kind: str, source_uri: str, quarantine_uri: str | None, error: str,
        message_id: str | None = None, raw_sha256: str | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                """INSERT INTO quarantine_events(
                   occurred_at, kind, source_uri, quarantine_uri, message_id, raw_sha256, error_text
                   ) VALUES(?,?,?,?,?,?,?)""",
                (utc_now(), kind, source_uri, quarantine_uri, message_id, raw_sha256, error),
            )
            return int(cursor.lastrowid)

    def put_decision(self, decision_id: str, title: str, status: str, body: str,
                     source_message_id: str | None = None, version: int | None = None) -> int:
        if status not in {"proposed", "accepted", "superseded", "rejected"}:
            raise ValueError("Geçersiz karar durumu")
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                "SELECT MAX(version) FROM decisions WHERE id=?", (decision_id,)
            ).fetchone()[0]
            next_version = version if version is not None else (latest or 0) + 1
            if next_version < 1 or (latest is not None and next_version <= latest):
                raise IntegrityConflict("Karar sürümü mevcut en son sürümden büyük olmalı")
            connection.execute(
                "INSERT INTO decisions(id,version,title,status,body,source_message_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (decision_id, next_version, title, status, body, source_message_id, now, now),
            )
            return next_version

    def get_decision(self, decision_id: str, version: int | None = None) -> sqlite3.Row | None:
        with self.connect() as connection:
            if version is None:
                return connection.execute(
                    "SELECT * FROM decisions WHERE id=? ORDER BY version DESC LIMIT 1", (decision_id,)
                ).fetchone()
            return connection.execute(
                "SELECT * FROM decisions WHERE id=? AND version=?", (decision_id, version)
            ).fetchone()

    def get_message(self, message_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
