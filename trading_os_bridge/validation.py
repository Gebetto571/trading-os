from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlparse


MESSAGE_KEYS = {
    "schema_version", "id", "created_at", "sender", "recipient", "type",
    "subject", "body", "correlation_id", "artifacts", "metadata",
}
LOCAL_ARTIFACT_KEYS = {"name", "uri", "sha256"}
EXTERNAL_ARTIFACT_KEYS = {"kind", "name", "url"}
VALID_TYPES = {"task", "response", "decision", "status", "error"}
MESSAGE_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas/message.schema.json"
MESSAGE_SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
DEFAULT_ROLES = {
    "orchestrator", "docs-manager", "cloud-planner", "codex-dev",
    "bridge-engineer", "operations-engineer", "governance-reviewer",
    "devils-advocate", "external-sync", "all-chats",
    "chatgpt", "codex-local", "chief-engineer",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$")
MAX_METADATA_BYTES = 16_384
DOMAINS = {f"{number:02d}" for number in range(9)}
CHANGE_MODES = {"FAST", "STANDARD", "STRICT"}
VERIFICATION_VERDICTS = {"ALIGNED", "CONDITIONAL", "BLOCKED"}
BRIEF_KEYS = {
    "outcome", "approved_logic", "in_scope", "non_goals", "acceptance_criteria",
    "required_tests", "risks", "stop_conditions",
}
LEGACY_BRIEF_KEYS = {"invariants", "assumptions", "evidence_references"}
RESULT_KEYS = {
    "verification_verdict", "changed_files", "commands", "git_state",
    "skipped_checks", "risks", "next_safe_step", "permission_state",
}
FORBIDDEN_METADATA_KEYS = {
    "api_key", "access_token", "secret_key", "private_key", "seed_phrase",
    "personal_data", "large_log", "raw_venue_payload",
}
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?im)\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|private[_-]?key|seed[_-]?phrase)"
    r"\s*[:=]\s*[^<\s][^\s]*"
)


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
    in_role_table = False
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not in_role_table:
            if stripped.startswith("| role_key |"):
                in_role_table = True
            continue
        if not stripped.startswith("|"):
            break
        match = re.match(r"\|\s*`([^`]+)`\s*\|", stripped)
        if match is not None:
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


def load_conversation_map(path: Path) -> dict[str, dict[str, str]]:
    document = parse_json_strict(path.read_bytes())
    if not isinstance(document, dict) or set(document) != {"schema_version", "authority", "model", "channels"}:
        raise ValueError("conversation-map alanları geçersiz")
    if document["schema_version"] != 1 or document["authority"] != "chief-engineer":
        raise ValueError("conversation-map sürümü veya otoritesi geçersiz")
    if document["model"] != "one-chief-engineer-domain-lanes" or not isinstance(document["channels"], list):
        raise ValueError("conversation-map modeli geçersiz")
    result: dict[str, dict[str, str]] = {}
    for item in document["channels"]:
        if not isinstance(item, dict) or set(item) != {"domain", "cloud_conversation_key", "local_lane"}:
            raise ValueError("conversation-map kanal alanları geçersiz")
        domain = item["domain"]
        if domain not in DOMAINS or domain in result:
            raise ValueError("conversation-map domain değeri geçersiz veya tekrarlı")
        expected = {
            "cloud_conversation_key": f"tos-cloud-{domain}",
            "local_lane": f"chief-engineer/{domain}",
        }
        if any(item[key] != value for key, value in expected.items()):
            raise ValueError(f"conversation-map {domain} hattı kanonik değil")
        result[domain] = dict(item)
    if set(result) != DOMAINS:
        raise ValueError("conversation-map 00-08 alanlarının tamamını içermeli")
    return result


def _string_list(value: object, field: str, maximum_items: int = 200) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise ValueError(f"{field} en fazla {maximum_items} öğeli bir liste olmalı")
    for index, item in enumerate(value):
        _require_string(item, f"{field}[{index}]", 1, 4096)
    return value


def _reject_forbidden_metadata(value: object, path: str = "metadata") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if normalized in FORBIDDEN_METADATA_KEYS:
                raise ValueError(f"{path}.{key} taşıma için yasak içerik alanıdır")
            _reject_forbidden_metadata(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_forbidden_metadata(nested, f"{path}[{index}]")


def _validate_chief_engineer_metadata(message: dict, conversation_map: dict[str, dict[str, str]]) -> None:
    metadata = message["metadata"]
    chief_fields = {"project_domain", "cloud_conversation_key", "local_lane", "authority", "approval_state"}
    if not chief_fields.intersection(metadata):
        return
    if not chief_fields.issubset(metadata):
        raise ValueError("Chief Engineer yönlendirme alanları eksik")
    domain = metadata["project_domain"]
    route = conversation_map.get(domain) if isinstance(domain, str) else None
    if route is None:
        raise ValueError("project_domain kayıtlı değil")
    if metadata["cloud_conversation_key"] != route["cloud_conversation_key"]:
        raise ValueError("cloud_conversation_key domain ile eşleşmiyor")
    if metadata["local_lane"] != route["local_lane"]:
        raise ValueError("local_lane domain ile eşleşmiyor")
    if metadata["authority"] != "chief-engineer":
        raise ValueError("authority chief-engineer olmalı")

    if message["type"] == "task":
        if message["sender"] != "chatgpt" or message["recipient"] != "codex-local":
            raise ValueError("Chief Engineer görevi chatgpt -> codex-local yönünde olmalı")
        if metadata["approval_state"] != "approved_for_local_implementation":
            raise ValueError("Chief Engineer görevi yerel uygulama için onaylı değil")
        if metadata.get("change_mode") not in CHANGE_MODES:
            raise ValueError("change_mode FAST, STANDARD veya STRICT olmalı")
        brief = metadata.get("implementation_brief")
        allowed_brief_profiles = {frozenset(BRIEF_KEYS), frozenset(BRIEF_KEYS | LEGACY_BRIEF_KEYS)}
        if not isinstance(brief, dict) or frozenset(brief) not in allowed_brief_profiles:
            raise ValueError("implementation_brief alanları eksik veya fazla")
        _require_string(brief["outcome"], "implementation_brief.outcome", 1, 4096)
        for key in BRIEF_KEYS - {"outcome"}:
            _string_list(brief[key], f"implementation_brief.{key}")
        for key in LEGACY_BRIEF_KEYS:
            if key in brief:
                _string_list(brief[key], f"implementation_brief.{key}")
    elif message["type"] in {"response", "status", "error"}:
        if message["sender"] != "codex-local" or message["recipient"] != "chatgpt":
            raise ValueError("Chief Engineer sonucu codex-local -> chatgpt yönünde olmalı")
        result = metadata.get("result")
        if not isinstance(result, dict) or set(result) != RESULT_KEYS:
            raise ValueError("Chief Engineer sonuç alanları eksik veya fazla")
        if result["verification_verdict"] not in VERIFICATION_VERDICTS:
            raise ValueError("verification_verdict geçersiz")
        _string_list(result["changed_files"], "result.changed_files")
        _string_list(result["skipped_checks"], "result.skipped_checks")
        _string_list(result["risks"], "result.risks")
        _require_string(result["next_safe_step"], "result.next_safe_step", 1, 4096)
        if not isinstance(result["commands"], list) or len(result["commands"]) > 200:
            raise ValueError("result.commands en fazla 200 öğeli bir liste olmalı")
        for index, command in enumerate(result["commands"]):
            if not isinstance(command, dict) or set(command) != {"command", "exit_code", "summary"}:
                raise ValueError(f"result.commands[{index}] alanları geçersiz")
            _require_string(command["command"], f"result.commands[{index}].command", 1, 4096)
            if type(command["exit_code"]) is not int:
                raise ValueError(f"result.commands[{index}].exit_code tam sayı olmalı")
            _require_string(command["summary"], f"result.commands[{index}].summary", 1, 4096)
        if not isinstance(result["git_state"], dict):
            raise ValueError("result.git_state nesne olmalı")
        permissions = result["permission_state"]
        expected_permissions = {"commit", "push", "merge", "deployment", "live_enablement"}
        if not isinstance(permissions, dict) or set(permissions) != expected_permissions:
            raise ValueError("result.permission_state alanları geçersiz")
        if any(value is not False for value in permissions.values()):
            raise ValueError("Bulut kabulü dış işlem yetkisi veremez")
    else:
        raise ValueError("Chief Engineer metadata bu mesaj türünde kullanılamaz")


def _schema_uuid(value: object) -> bool:
    try:
        _uuid(value, "schema UUID")
    except ValueError:
        return False
    return True


def _schema_utc_z(value: object) -> bool:
    if not isinstance(value, str) or not 20 <= len(value) <= 32 or not UTC_Z_RE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _schema_safe_body(value: object) -> bool:
    return isinstance(value, str) and not (
        PRIVATE_KEY_RE.search(value) or SECRET_ASSIGNMENT_RE.search(value)
    )


def _schema_safe_uri(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    if parsed.scheme not in {"file", "https", "git"}:
        return False
    for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
        normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
        if normalized in FORBIDDEN_METADATA_KEYS:
            return False
    return True


def _schema_safe_metadata(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        _reject_forbidden_metadata(value)
        return len(canonical_bytes(value)) <= MAX_METADATA_BYTES
    except (TypeError, ValueError):
        return False


def _schema_strict_integer(value: object) -> bool:
    return type(value) is int


def _schema_format_checker():
    try:
        from jsonschema import FormatChecker
    except ImportError as error:
        raise ValueError("Draft 2020-12 validator bağımlılığı kullanılamıyor") from error

    checker = FormatChecker()
    checker.checks("trading-os-uuid")(_schema_uuid)
    checker.checks("trading-os-utc-z")(_schema_utc_z)
    checker.checks("trading-os-safe-body")(_schema_safe_body)
    checker.checks("trading-os-safe-uri")(_schema_safe_uri)
    checker.checks("trading-os-safe-metadata")(_schema_safe_metadata)
    checker.checks("trading-os-strict-integer")(_schema_strict_integer)
    return checker


def _assert_local_schema_references(value: object, location: str = "$") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_location = f"{location}.{key}"
            if key == "$ref" and (not isinstance(nested, str) or not nested.startswith("#")):
                raise ValueError(f"JSON Schema yalnız yerel $ref kullanabilir: {nested_location}")
            _assert_local_schema_references(nested, nested_location)
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _assert_local_schema_references(nested, f"{location}[{index}]")


def _schema_formats(value: object) -> set[str]:
    if isinstance(value, dict):
        formats = {nested for key, nested in value.items() if key == "format" and isinstance(nested, str)}
        for nested in value.values():
            formats.update(_schema_formats(nested))
        return formats
    if isinstance(value, list):
        formats: set[str] = set()
        for nested in value:
            formats.update(_schema_formats(nested))
        return formats
    return set()


def load_message_schema(schema_path: Path | None = None) -> dict:
    path = schema_path or MESSAGE_SCHEMA_PATH
    document = parse_json_strict(path.read_bytes())
    if not isinstance(document, dict) or document.get("$schema") != MESSAGE_SCHEMA_DRAFT:
        raise ValueError("message.schema.json Draft 2020-12 sözleşmesi değil")
    _assert_local_schema_references(document)
    return document


def validate_schema_message(message: object, schema_path: Path | None = None) -> dict:
    try:
        from jsonschema import Draft202012Validator, SchemaError
    except ImportError as error:
        raise ValueError("Draft 2020-12 validator bağımlılığı kullanılamıyor") from error

    schema = load_message_schema(schema_path)
    checker = _schema_format_checker()
    unsupported = _schema_formats(schema) - set(checker.checkers)
    if unsupported:
        raise ValueError("JSON Schema desteklenmeyen format kullanıyor: " + ", ".join(sorted(unsupported)))
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as error:
        raise ValueError(f"JSON Schema Draft 2020-12 geçersiz: {error.message}") from error
    validator = Draft202012Validator(schema, format_checker=checker)
    errors = sorted(
        validator.iter_errors(message),
        key=lambda error: (tuple(str(item) for item in error.absolute_path), error.message),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(item) for item in first.absolute_path) or "$"
        raise ValueError(f"JSON Schema v1 reddi ({path}): {first.message}")
    if not isinstance(message, dict):
        raise ValueError("JSON Schema geçerli olmayan mesaj nesnesi")
    return message


def validate_schema_raw(raw: bytes, schema_path: Path | None = None) -> dict:
    return validate_schema_message(parse_json_strict(raw), schema_path)


def validate_message(
    message: object, roles: set[str] | None = None,
    conversation_map: dict[str, dict[str, str]] | None = None,
) -> dict:
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
    body = _require_string(message["body"], "body", 0, 100_000)
    if PRIVATE_KEY_RE.search(body) or SECRET_ASSIGNMENT_RE.search(body):
        raise ValueError("body taşıma için yasak sır benzeri içerik taşıyor")
    _uuid(message["correlation_id"], "correlation_id", nullable=True)
    artifacts = message["artifacts"]
    if not isinstance(artifacts, list) or len(artifacts) > 100:
        raise ValueError("artifacts en fazla 100 öğeli bir liste olmalı")
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict) or (
            set(artifact) != LOCAL_ARTIFACT_KEYS and set(artifact) != EXTERNAL_ARTIFACT_KEYS
        ):
            raise ValueError(f"artifacts[{index}] alanları desteklenen zarf biçimiyle eşleşmiyor")
        _require_string(artifact["name"], f"artifacts[{index}].name", 1, 255)
        uri_field = "uri" if "uri" in artifact else "url"
        uri = _require_string(artifact[uri_field], f"artifacts[{index}].{uri_field}", 1, 2048)
        parsed = urlparse(uri)
        if parsed.scheme not in {"file", "https", "git"}:
            raise ValueError(f"artifacts[{index}].{uri_field} izinli URI şemasına sahip değil")
        for key, _ in parse_qsl(parsed.query, keep_blank_values=True):
            normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
            if normalized in FORBIDDEN_METADATA_KEYS:
                raise ValueError(f"artifacts[{index}] URL'si yasak sır parametresi taşıyor")
        if "sha256" in artifact:
            digest = artifact["sha256"]
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ValueError(f"artifacts[{index}].sha256 geçerli değil")
        else:
            _require_string(artifact["kind"], f"artifacts[{index}].kind", 1, 80)
    if not isinstance(message["metadata"], dict):
        raise ValueError("metadata bir nesne olmalı")
    _reject_forbidden_metadata(message["metadata"])
    if len(canonical_bytes(message["metadata"])) > MAX_METADATA_BYTES:
        raise ValueError(f"metadata en fazla {MAX_METADATA_BYTES} bayt olmalı")
    if conversation_map is not None:
        _validate_chief_engineer_metadata(message, conversation_map)
    return message


def canonical_bytes(message: dict) -> bytes:
    return json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
