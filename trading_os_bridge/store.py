from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self, database: Path, migrations: Path) -> None:
        self.database = database
        self.migrations = migrations

    def connect(self) -> sqlite3.Connection:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
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

    def put_message(self, message: dict, direction: str, status: str, source_uri: str | None = None) -> bool:
        now = utc_now()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO messages (
                    id, schema_version, created_at, received_at, sender, recipient,
                    message_type, subject, body, correlation_id, direction, status,
                    source_uri, payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["id"], message["schema_version"], message["created_at"],
                    now if direction == "inbound" else None, message["sender"], message["recipient"],
                    message["type"], message["subject"], message["body"], message.get("correlation_id"),
                    direction, status, source_uri, json.dumps(message, ensure_ascii=False, sort_keys=True), now,
                ),
            )
            if cursor.rowcount:
                for artifact in message.get("artifacts", []):
                    connection.execute(
                        "INSERT INTO artifacts(message_id, name, uri, sha256, created_at) VALUES (?, ?, ?, ?, ?)",
                        (message["id"], artifact["name"], artifact["uri"], artifact.get("sha256"), now),
                    )
            return bool(cursor.rowcount)

    def list_messages(self, limit: int = 25) -> list[sqlite3.Row]:
        with self.connect() as connection:
            return list(
                connection.execute(
                    "SELECT id, created_at, sender, recipient, message_type, status, subject FROM messages ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
            )

    def update_status(self, message_id: str, status: str) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE messages SET status = ?, updated_at = ? WHERE id = ?",
                (status, utc_now(), message_id),
            )
            return bool(cursor.rowcount)

    def get_message(self, message_id: str) -> sqlite3.Row | None:
        with self.connect() as connection:
            return connection.execute(
                """
                SELECT id, created_at, received_at, sender, recipient, message_type,
                       status, subject, correlation_id, direction, source_uri, updated_at
                FROM messages WHERE id = ?
                """,
                (message_id,),
            ).fetchone()
