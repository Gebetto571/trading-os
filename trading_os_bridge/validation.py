from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


MESSAGE_KEYS = {
    "schema_version", "id", "created_at", "sender", "recipient", "type",
    "subject", "body", "correlation_id", "artifacts", "metadata",
}
ARTIFACT_KEYS = {"name", "uri", "sha256"}
VALID_TYPES = {"task", "response", "decision", "status", "error"}
DEFAULT_ROLES = {
    "orchestrator", "docs-manager", "cloud-planner", "codex-dev",
    "bridge-engineer", "operations-engineer", "governance-reviewer",
    "devils-advocate", "external-sync", "all-chats",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
MAX_METADATA_BYTES = 16_384


def parse_json_strict(raw: bytes) -> object:
    def unique_object(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Tekrarlanan JSON anahtarı: {key}")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object)


def load_registry_roles(registry_path: Path | None = None) -> set[str]:
    roles = set(DEFAULT_ROLES)
    if registry_path is None or not registry_path.is_file():
        return roles
    for match in re.finditer(r"^\|\s*`([^`]+)`\s*\|", registry_path.read_text(encoding="utf-8"), re.MULTILINE):
        roles.add(match.group(1))
    return roles


def _require_string(value: object, field: str, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} metin olmalı ve uzunluğu {minimum}-{maximum} olmalı")
    return value


def _uuid(value: object, field: str, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} UUID olmalı")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise ValueError(f"{field} UUID olmalı") from error
    if str(parsed) != value.lower():
        raise ValueError(f"{field} standart UUID biçiminde olmalı")


def validate_message(message: object, roles: set[str] | None = None) -> dict:
    if not isinstance(message, dict):
        raise ValueError("Mesaj bir JSON nesnesi olmalı")
    keys = set(message)
    if keys != MESSAGE_KEYS:
        missing, extra = MESSAGE_KEYS - keys, keys - MESSAGE_KEYS
        details = []
        if missing:
            details.append("eksik: " + ", ".join(sorted(missing)))
        if extra:
            details.append("fazla: " + ", ".join(sorted(extra)))
        raise ValueError("Mesaj alanları v1 şemasıyla birebir eşleşmiyor (" + "; ".join(details) + ")")
    if type(message["schema_version"]) is not int or message["schema_version"] != 1:
        raise ValueError("schema_version tam sayı 1 olmalı")
    _uuid(message["id"], "id")
    created_at = _require_string(message["created_at"], "created_at", 20, 32)
    if not UTC_Z_RE.fullmatch(created_at):
        raise ValueError("created_at UTC-Z RFC3339 biçiminde olmalı")
    try:
        datetime.fromisoformat(created_at[:-1] + "+00:00")
    except ValueError as error:
        raise ValueError("created_at geçerli bir tarih olmalı") from error
    allowed_roles = roles or DEFAULT_ROLES
    for field in ("sender", "recipient"):
        role = _require_string(message[field], field, 1, 80)
        if role not in allowed_roles:
            raise ValueError(f"{field} kayıtlı bir sohbet rolü değil: {role}")
    if message["sender"] == "all-chats":
        raise ValueError("all-chats sanal hedefi gönderen olamaz")
    if message["type"] not in VALID_TYPES:
        raise ValueError("Desteklenmeyen mesaj türü")
    if message["recipient"] == "all-chats" and message["type"] in {"task", "response", "error"}:
        raise ValueError("all-chats işlem gerektiren mesajların alıcısı olamaz")
    _require_string(message["subject"], "subject", 1, 240)
    _require_string(message["body"], "body", 0, 100_000)
    _uuid(message["correlation_id"], "correlation_id", nullable=True)
    artifacts = message["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > 100:
        raise ValueError("artifacts en fazla 100 öğeli bir liste olmalı")
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict) or set(artifact) != ARTIFACT_KEYS:
            raise ValueError(f"artifacts[{index}] alanları v1 şemasıyla birebir eşleşmiyor")
        _require_string(artifact["name"], f"artifacts[{index}].name", 1, 255)
        uri = _require_string(artifact["uri"], f"artifacts[{index}].uri", 1, 2048)
        parsed = urlparse(uri)
        if parsed.scheme not in {"file", "https", "git"}:
            raise ValueError(f"artifacts[{index}].uri izinli URI şemasına sahip değil")
        digest = artifact["sha256"]
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ValueError(f"artifacts[{index}].sha256 geçerli değil")
    if not isinstance(message["metadata"], dict):
        raise ValueError("metadata bir nesne olmalı")
    if len(canonical_bytes(message["metadata"])) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata en fazla {MAX_METADATA_BYTES} bayt olmalı")
    return message


def canonical_bytes(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
