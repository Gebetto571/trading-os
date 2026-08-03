from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .validation import canonical_bytes, sha256_bytes


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class IntegrityConflict(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


TRANSITIONS = {
    "queued": {"received", "processing", "failed"},
    "received": {"processing", "failed"},
    "processing": {"completed", "failed"},
    "completed": set(),
    "failed": set(),
}


class Store:
    def __init__(self, database: Path, migrations: Path) -> None:
        self.database = database
        self.migrations = migrations

    def connect(self, timeout: float = 5.0) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database, timeout=timeout)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def migrate(self) -> int:
        applied = 0
        with self.connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            known = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            for path in sorted(self.migrations.glob("[0-9][0-9][0-9]_*.sql")):
                version = int(path.name.split("_", 1)[0])
                if version in known:
                    continue
                connection.executescript(path.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                    (version, utc_now()),
                )
                applied += 1
        return applied

    def put_message(
        self, message: dict, direction: str, status: str, source_uri: str | None = None,
        raw_payload: bytes | None = None,
    ) -> bool:
        now = utc_now()
        canonical = canonical_bytes(message)
        payload_sha = sha256_bytes(canonical)
        raw_sha = sha256_bytes(raw_payload if raw_payload is not None else canonical)
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
                    source_uri, payload_json, payload_sha256, raw_sha256, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["id"], message["schema_version"], message["created_at"],
                    now if direction == "inbound" else None, message["sender"], message["recipient"],
                    message["type"], message["subject"], message["body"], message["correlation_id"],
                    direction, status, source_uri,
                    json.dumps(message, ensure_ascii=False, sort_keys=True), payload_sha, raw_sha, now,
                ),
            )
            for artifact in message["artifacts"]:
                connection.execute(
                    "INSERT INTO artifacts(message_id, name, uri, sha256, created_at) VALUES (?, ?, ?, ?, ?)",
                    (message["id"], artifact["name"], artifact["uri"], artifact["sha256"], now),
                )
            return True

    def list_messages(self, limit: int = 25) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(connection.execute(
                "SELECT id, created_at, sender, recipient, message_type, status, subject FROM messages ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ))

    def update_status(self, message_id: str, status: str, error: str | None = None) -> bool:
        with self.connect() as connection:
            row = connection.execute("SELECT status FROM messages WHERE id = ?", (message_id,)).fetchone()
            if row is None:
                return False
            current = row["status"]
            if status == current:
                return True
            if status not in TRANSITIONS.get(current, set()):
                raise InvalidTransition(f"İzin verilmeyen durum geçişi: {current} -> {status}")
            connection.execute(
                """UPDATE messages SET status = ?, last_error = ?,
                   claimed_by = CASE WHEN ? IN ('completed','failed') THEN NULL ELSE claimed_by END,
                   lease_until = CASE WHEN ? IN ('completed','failed') THEN NULL ELSE lease_until END,
                   updated_at = ? WHERE id = ?""",
                (status, error, status, status, utc_now(), message_id),
            )
            return True

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

    def recover_expired(self, reason: str = "lease expired") -> int:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """UPDATE messages SET status='received', claimed_by=NULL, claimed_at=NULL,
                   lease_until=NULL, last_error=?, updated_at=?
                   WHERE status='processing' AND lease_until IS NOT NULL AND lease_until <= ?""",
                (reason, now, now),
            )
            return cursor.rowcount

    def recover_message(self, message_id: str, reason: str = "manual recovery") -> bool:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status, lease_until FROM messages WHERE id=?", (message_id,)
            ).fetchone()
            if row is None:
                return False
            recoverable = row["status"] == "failed" or (
                row["status"] == "processing" and row["lease_until"] is not None and row["lease_until"] <= now
            )
            if not recoverable:
                raise InvalidTransition(f"Mesaj kurtarılabilir durumda değil: {row['status']}")
            connection.execute(
                """UPDATE messages SET status='received', claimed_by=NULL, claimed_at=NULL,
                   lease_until=NULL, last_error=?, updated_at=? WHERE id=?""",
                (reason, now, message_id),
            )
            return True

    def mark_quarantine(self, message_id: str, uri: str, error: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE messages SET quarantined_at=?, quarantine_uri=?, last_error=?, updated_at=? WHERE id=?",
                (utc_now(), uri, error, utc_now(), message_id),
            )

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
