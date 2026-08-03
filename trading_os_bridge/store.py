from __future__ import annotations

import json
import os
import sqlite3
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
            row = connection.execute(
                "SELECT status, direction, claimed_by, lease_until FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            if row is None:
                return False
            current = row["status"]
            if current == "processing" and status in {"completed", "failed"}:
                if not worker:
                    raise InvalidTransition("Terminal durum için claim sahibi worker zorunlu")
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

    def claim_chief_engineer_task(
        self, lane: str, base_commit: str, owned_paths: list[str], lease_seconds: int = 300,
    ) -> sqlite3.Row | None:
        if not lane or not base_commit or lease_seconds < 1:
            raise ValueError("lane, base_commit ve pozitif lease_seconds gerekli")
        paths = self._normalize_owned_paths(owned_paths)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
        lease = (now_dt + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT id FROM messages
                   WHERE direction='inbound' AND status='received' AND message_type='task'
                     AND authority='chief-engineer'
                     AND approval_state='approved_for_local_implementation'
                     AND local_lane=?
                   ORDER BY created_at, id LIMIT 1""",
                (lane,),
            ).fetchone()
            if row is None:
                return None
            active = connection.execute(
                """SELECT id, owned_paths_json FROM messages
                   WHERE direction='inbound' AND status='processing' AND active_writer='chief-engineer'"""
            )
            for item in active:
                other = json.loads(item["owned_paths_json"] or "[]")
                if self._paths_overlap(paths, other):
                    raise OwnershipConflict(
                        f"Dosya sahipliği çakışıyor: {row['id']} ile aktif {item['id']}"
                    )
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

    def link_result(self, task_id: str, result_id: str) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE messages SET result_message_id=?, revision=revision+1,
                   updated_by='chief-engineer', updated_at=?
                   WHERE id=? AND direction='inbound' AND status='processing'
                     AND active_writer='chief-engineer' AND result_message_id IS NULL""",
                (result_id, now, task_id),
            )
            return cursor.rowcount == 1

    def recover_expired(self, reason: str = "lease expired") -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE messages SET status='received', claimed_by=NULL, claimed_at=NULL,
                   lease_until=NULL, revision=revision+1, updated_by='recovery', last_error=?, updated_at=?
                   WHERE status='processing' AND lease_until IS NOT NULL AND lease_until <= ?""",
                (reason, now, now),
            )
            return cursor.rowcount

    def recover_message(self, message_id: str, reason: str = "manual recovery") -> bool:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, direction, lease_until FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if row is None:
                return False
            if row["direction"] != "inbound":
                raise InvalidTransition("Yalnız inbound mesaj sahipliği kurtarılabilir")
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
