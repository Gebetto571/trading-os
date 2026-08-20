import copy
import json
import tempfile
import unittest
import uuid
from pathlib import Path

from trading_os_bridge import cli
from trading_os_bridge.validation import (
    DEFAULT_ROLES, MAX_METADATA_BYTES, canonical_bytes, load_conversation_map,
    load_message_schema, load_registry_roles, parse_json_strict, sha256_bytes,
    validate_message, validate_schema_message, validate_schema_raw,
)


ROOT = Path(__file__).parents[1]
CONVERSATION_MAP = load_conversation_map(ROOT / "schemas/conversation-map.json")
REGISTRY_PATH = ROOT / "docs/decisions/system/TOS-CHAT-REGISTRY__v1.0.md"
SCHEMA_PATH = ROOT / "schemas/message.schema.json"


def valid_message():
    return {
        "schema_version": 1,
        "id": str(uuid.uuid4()),
        "created_at": "2026-08-03T12:00:00Z",
        "sender": "cloud-planner",
        "recipient": "codex-dev",
        "type": "task",
        "subject": "Test",
        "body": "Body",
        "correlation_id": None,
        "artifacts": [{"name": "x", "uri": "https://example.test/x", "sha256": "a" * 64}],
        "metadata": {},
    }


def chief_engineer_task(domain="00"):
    item = valid_message()
    item.update(sender="chatgpt", recipient="codex-local")
    item["artifacts"] = [{
        "kind": "external_document", "name": "brief.md", "url": "https://example.test/brief",
    }]
    item["metadata"] = {
        "project_domain": domain,
        "cloud_conversation_key": f"tos-cloud-{domain}",
        "local_lane": f"chief-engineer/{domain}",
        "authority": "chief-engineer",
        "approval_state": "approved_for_local_implementation",
        "change_mode": "STANDARD",
        "implementation_brief": {
            "outcome": "Outcome",
            "approved_logic": ["Logic"],
            "in_scope": ["Scope"],
            "non_goals": ["Non-goal"],
            "acceptance_criteria": ["Criterion"],
            "required_tests": ["Test"],
            "risks": ["Risk"],
            "stop_conditions": ["Stop"],
        },
    }
    return item


def chief_engineer_result(message_type="response", domain="00"):
    item = chief_engineer_task(domain)
    item.update(
        id=str(uuid.uuid4()), sender="codex-local", recipient="chatgpt",
        type=message_type, correlation_id=str(uuid.uuid4()),
    )
    item["metadata"] = {
        "project_domain": domain,
        "cloud_conversation_key": f"tos-cloud-{domain}",
        "local_lane": f"chief-engineer/{domain}",
        "authority": "chief-engineer",
        "approval_state": "implemented_locally",
        "updated_by": "chief-engineer",
        "base_commit": "7c5224ea63b23aac0f14bfb33130e5318416051d",
        "active_writer": "chief-engineer",
        "owned_paths": ["schemas/message.schema.json"],
        "revision": 1,
        "result": {
            "verification_verdict": "ALIGNED",
            "changed_files": ["schemas/message.schema.json"],
            "commands": [{"command": "python -m unittest", "exit_code": 0, "summary": "passed"}],
            "git_state": {"branch": "main", "commit_created": False},
            "skipped_checks": [],
            "risks": [],
            "next_safe_step": "Cloud readback",
            "permission_state": {
                "commit": False, "push": False, "merge": False,
                "deployment": False, "live_enablement": False,
            },
        },
    }
    return item


def legacy_chief_engineer_task(domain="00"):
    item = chief_engineer_task(domain)
    item["metadata"]["implementation_brief"].update({
        "invariants": ["Fail closed"],
        "assumptions": ["Offline only"],
        "evidence_references": ["archive/v1"],
    })
    return item


def raw_message(item):
    return json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class ValidationTests(unittest.TestCase):
    def test_valid_and_canonical_hash_is_key_order_independent(self):
        message = valid_message()
        validate_message(message)
        reversed_message = dict(reversed(list(message.items())))
        self.assertEqual(sha256_bytes(canonical_bytes(message)), sha256_bytes(canonical_bytes(reversed_message)))

    def test_exact_keys(self):
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation):
                message = valid_message()
                if mutation == "missing":
                    del message["body"]
                else:
                    message["unexpected"] = True
                with self.assertRaises(ValueError):
                    validate_message(message)

    def test_datetime_uuid_roles_and_types_are_strict(self):
        cases = [
            ("created_at", "2026-08-03T12:00:00+03:00"),
            ("id", "not-a-uuid"),
            ("correlation_id", "not-a-uuid"),
            ("sender", "unknown"),
            ("recipient", "unknown"),
            ("type", "advice"),
            ("metadata", []),
        ]
        for field, value in cases:
            with self.subTest(field=field):
                message = valid_message()
                message[field] = value
                with self.assertRaises(ValueError):
                    validate_message(message)

    def test_registry_roles_and_virtual_role_constraints(self):
        message = valid_message()
        message["sender"] = "bridge-engineer"
        message["recipient"] = "operations-engineer"
        validate_message(message)
        message["sender"] = "all-chats"
        with self.assertRaises(ValueError):
            validate_message(message)
        message = valid_message()
        message["recipient"] = "all-chats"
        with self.assertRaises(ValueError):
            validate_message(message)
        message["type"] = "status"
        validate_message(message)
        message = valid_message()
        message["sender"] = "external-sync"
        validate_message(message)

    def test_lengths_and_artifacts(self):
        message = valid_message()
        message["subject"] = ""
        with self.assertRaises(ValueError):
            validate_message(message)
        for artifact in (
            {"name": "x", "uri": "javascript:bad", "sha256": None},
            {"name": "x", "uri": "drive://file-id", "sha256": "a" * 64},
            {"name": "x", "uri": "file:///tmp/x", "sha256": None},
            {"name": "x", "uri": "file:///tmp/x", "sha256": "BAD"},
            {"name": "x", "uri": "file:///tmp/x", "sha256": None, "extra": 1},
        ):
            with self.subTest(artifact=artifact):
                candidate = valid_message()
                candidate["artifacts"] = [copy.deepcopy(artifact)]
                with self.assertRaises(ValueError):
                    validate_message(candidate)

    def test_duplicate_json_keys_and_large_metadata_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_json_strict(b'{"id":"first","id":"second"}')
        message = valid_message()
        message["metadata"] = {"large": "x" * 17_000}
        with self.assertRaises(ValueError):
            validate_message(message)

    def test_all_chief_engineer_domain_routes_are_validated(self):
        self.assertEqual(set(CONVERSATION_MAP), {f"{number:02d}" for number in range(9)})
        for domain in sorted(CONVERSATION_MAP):
            with self.subTest(domain=domain):
                validate_message(chief_engineer_task(domain), conversation_map=CONVERSATION_MAP)

    def test_chief_engineer_task_fails_closed_on_route_approval_and_sensitive_metadata(self):
        mutations = (
            ("local_lane", "chief-engineer/08"),
            ("cloud_conversation_key", "tos-cloud-08"),
            ("approval_state", "draft"),
            ("authority", "codex-dev"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                item = chief_engineer_task("00")
                item["metadata"][field] = value
                with self.assertRaises(ValueError):
                    validate_message(item, conversation_map=CONVERSATION_MAP)
        item = chief_engineer_task("00")
        item["metadata"]["api_key"] = "must-not-travel"
        with self.assertRaises(ValueError):
            validate_message(item, conversation_map=CONVERSATION_MAP)
        item = chief_engineer_task("00")
        item["body"] = "access_token=must-not-travel"
        with self.assertRaises(ValueError):
            validate_message(item, conversation_map=CONVERSATION_MAP)
        item = chief_engineer_task("00")
        item["artifacts"][0]["url"] = "https://example.test/brief?access_token=must-not-travel"
        with self.assertRaises(ValueError):
            validate_message(item, conversation_map=CONVERSATION_MAP)

    def test_chief_engineer_result_requires_safe_permission_boundary(self):
        item = chief_engineer_task("03")
        item.update(
            id=str(uuid.uuid4()), sender="codex-local", recipient="chatgpt",
            type="response", correlation_id=str(uuid.uuid4()),
        )
        item["metadata"] = {
            "project_domain": "03",
            "cloud_conversation_key": "tos-cloud-03",
            "local_lane": "chief-engineer/03",
            "authority": "chief-engineer",
            "approval_state": "implemented_locally",
            "result": {
                "verification_verdict": "ALIGNED",
                "changed_files": ["trading_os_bridge/store.py"],
                "commands": [{"command": "python3 -m unittest", "exit_code": 0, "summary": "passed"}],
                "git_state": {"branch": "main", "commit_created": False},
                "skipped_checks": [],
                "risks": [],
                "next_safe_step": "Cloud readback",
                "permission_state": {
                    "commit": False, "push": False, "merge": False,
                    "deployment": False, "live_enablement": False,
                },
            },
        }
        validate_message(item, conversation_map=CONVERSATION_MAP)
        item["metadata"]["result"]["permission_state"]["commit"] = True
        with self.assertRaises(ValueError):
            validate_message(item, conversation_map=CONVERSATION_MAP)


class StaticRuntimeParityTests(unittest.TestCase):
    def _runtime_validate_raw(self, raw):
        return cli._validate(parse_json_strict(raw))

    def _accepts(self, operation):
        try:
            operation()
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return False
        return True

    def assert_parity_raw(self, raw, expected, label):
        static = self._accepts(lambda: validate_schema_raw(raw))
        runtime = self._accepts(lambda: self._runtime_validate_raw(raw))
        self.assertEqual(static, runtime, label)
        self.assertEqual(static, expected, label)

    @staticmethod
    def _metadata_with_exact_byte_length(length):
        empty = canonical_bytes({"padding": ""})
        if length < len(empty):
            raise ValueError("metadata hedefi çok küçük")
        result = {"padding": "x" * (length - len(empty))}
        if len(canonical_bytes(result)) != length:
            raise ValueError("metadata byte uzunluğu eşleşmedi")
        return result

    def test_schema_sources_match_runtime_registries(self):
        schema = load_message_schema(SCHEMA_PATH)
        self.assertEqual(load_registry_roles(REGISTRY_PATH), DEFAULT_ROLES)
        self.assertEqual(
            set(schema["properties"]["sender"]["enum"]),
            DEFAULT_ROLES - {"all-chats"},
        )
        self.assertEqual(
            set(schema["properties"]["recipient"]["enum"]),
            DEFAULT_ROLES,
        )
        self.assertEqual(set(CONVERSATION_MAP), {f"{number:02d}" for number in range(9)})

    def test_valid_v1_profiles_have_static_runtime_parity(self):
        cases = [("generic", valid_message())]
        cases.extend((f"chief-task-{domain}", chief_engineer_task(domain)) for domain in sorted(CONVERSATION_MAP))
        cases.extend((f"chief-{kind}", chief_engineer_result(kind)) for kind in ("response", "status", "error"))
        cases.append(("legacy-brief", legacy_chief_engineer_task()))

        for sender in sorted(DEFAULT_ROLES - {"all-chats"}):
            item = valid_message()
            item["sender"] = sender
            cases.append((f"registered-sender-{sender}", item))
        for recipient in sorted(DEFAULT_ROLES):
            item = valid_message()
            item["recipient"] = recipient
            if recipient == "all-chats":
                item["type"] = "status"
            cases.append((f"registered-recipient-{recipient}", item))

        for name, artifact in (
            ("local-file", {"name": "x", "uri": "file:///tmp/x", "sha256": "a" * 64}),
            ("local-https", {"name": "x", "uri": "https://example.test/x", "sha256": "a" * 64}),
            ("local-git", {"name": "x", "uri": "git:repo/path", "sha256": "a" * 64}),
            ("external-file", {"kind": "external", "name": "x", "url": "file:///tmp/x"}),
            ("external-https", {"kind": "external", "name": "x", "url": "https://example.test/x"}),
            ("external-git", {"kind": "external", "name": "x", "url": "git:repo/path"}),
        ):
            item = valid_message()
            item["artifacts"] = [artifact]
            cases.append((name, item))

        unicode_metadata = valid_message()
        unicode_metadata["metadata"] = {"note": "ü" * 8000}
        self.assertLessEqual(len(canonical_bytes(unicode_metadata["metadata"])), MAX_METADATA_BYTES)
        cases.append(("unicode-metadata", unicode_metadata))

        boundary_metadata = valid_message()
        boundary_metadata["metadata"] = self._metadata_with_exact_byte_length(MAX_METADATA_BYTES)
        cases.append(("metadata-exact-boundary", boundary_metadata))

        for name, item in cases:
            with self.subTest(name=name):
                self.assert_parity_raw(raw_message(item), True, name)

    def test_invalid_v1_profiles_fail_closed_in_both_layers(self):
        cases = []
        missing = valid_message()
        del missing["body"]
        cases.append(("missing-top-level", raw_message(missing)))
        extra = valid_message()
        extra["unexpected"] = True
        cases.append(("extra-top-level", raw_message(extra)))
        wrong_version = valid_message()
        wrong_version["schema_version"] = 2
        cases.append(("version", raw_message(wrong_version)))
        float_version = valid_message()
        float_version["schema_version"] = 1.0
        cases.append(("float-version", raw_message(float_version)))
        bad_uuid = valid_message()
        bad_uuid["id"] = "not-a-uuid"
        cases.append(("uuid", raw_message(bad_uuid)))
        bad_date = valid_message()
        bad_date["created_at"] = "2026-02-30T12:00:00Z"
        cases.append(("date", raw_message(bad_date)))
        unknown_role = valid_message()
        unknown_role["sender"] = "00 — Ana Kararlar ve Yol Haritası"
        cases.append(("unintended-registry-role", raw_message(unknown_role)))
        all_chats_sender = valid_message()
        all_chats_sender["sender"] = "all-chats"
        cases.append(("all-chats-sender", raw_message(all_chats_sender)))
        all_chats_task = valid_message()
        all_chats_task["recipient"] = "all-chats"
        cases.append(("all-chats-task", raw_message(all_chats_task)))
        partial_route = valid_message()
        partial_route["metadata"] = {"project_domain": "00"}
        cases.append(("partial-route", raw_message(partial_route)))
        mismatched_route = chief_engineer_task()
        mismatched_route["metadata"]["local_lane"] = "chief-engineer/08"
        cases.append(("route-mismatch", raw_message(mismatched_route)))
        chief_decision = chief_engineer_task()
        chief_decision["type"] = "decision"
        cases.append(("chief-decision", raw_message(chief_decision)))
        missing_brief = chief_engineer_task()
        del missing_brief["metadata"]["implementation_brief"]["risks"]
        cases.append(("brief-missing", raw_message(missing_brief)))
        extra_brief = chief_engineer_task()
        extra_brief["metadata"]["implementation_brief"]["unexpected"] = []
        cases.append(("brief-extra", raw_message(extra_brief)))
        wrong_brief_list = chief_engineer_task()
        wrong_brief_list["metadata"]["implementation_brief"]["risks"] = "not-a-list"
        cases.append(("brief-list", raw_message(wrong_brief_list)))
        float_exit_code = chief_engineer_result()
        float_exit_code["metadata"]["result"]["commands"][0]["exit_code"] = 1.0
        cases.append(("result-float-exit-code", raw_message(float_exit_code)))
        bad_git_state = chief_engineer_result()
        bad_git_state["metadata"]["result"]["git_state"] = []
        cases.append(("result-git-state", raw_message(bad_git_state)))
        bad_permission = chief_engineer_result()
        bad_permission["metadata"]["result"]["permission_state"]["commit"] = True
        cases.append(("result-permission", raw_message(bad_permission)))
        secret_body = valid_message()
        secret_body["body"] = "api_key=must-not-travel"
        cases.append(("secret-body", raw_message(secret_body)))
        secret_metadata = valid_message()
        secret_metadata["metadata"] = {"API-key": "must-not-travel"}
        cases.append(("secret-metadata", raw_message(secret_metadata)))
        secret_query = valid_message()
        secret_query["artifacts"] = [{
            "kind": "external", "name": "x",
            "url": "https://example.test/x?access%5Ftoken=must-not-travel",
        }]
        cases.append(("secret-query", raw_message(secret_query)))
        bad_artifact = valid_message()
        bad_artifact["artifacts"] = [{"name": "x", "uri": "javascript:bad", "sha256": "a" * 64}]
        cases.append(("artifact-scheme", raw_message(bad_artifact)))
        oversized_metadata = valid_message()
        oversized_metadata["metadata"] = self._metadata_with_exact_byte_length(MAX_METADATA_BYTES + 1)
        cases.append(("metadata-overflow", raw_message(oversized_metadata)))
        cases.append(("duplicate-json-key", b'{"schema_version":1,"schema_version":1}'))
        cases.append(("invalid-utf8", b'\xff'))

        for name, raw in cases:
            with self.subTest(name=name):
                self.assert_parity_raw(raw, False, name)

    def test_historical_v1_profiles_remain_accepted(self):
        for name, item in (
            ("historical-current-brief", chief_engineer_task()),
            ("historical-legacy-brief", legacy_chief_engineer_task()),
            ("historical-cli-response", chief_engineer_result()),
        ):
            with self.subTest(name=name):
                self.assert_parity_raw(raw_message(item), True, name)

    def test_local_historical_envelopes_have_parity_when_available(self):
        candidates = []
        for directory in (ROOT / "var/archive", ROOT / "var/outbox"):
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json")):
                raw = path.read_bytes()
                try:
                    parsed = parse_json_strict(raw)
                except ValueError:
                    continue
                if isinstance(parsed, dict) and set(parsed) == {
                    "schema_version", "id", "created_at", "sender", "recipient", "type",
                    "subject", "body", "correlation_id", "artifacts", "metadata",
                }:
                    candidates.append((path.name, raw))
        if not candidates:
            self.skipTest("Yerel historical V1 zarfı yok")
        for name, raw in candidates:
            with self.subTest(name=name):
                self.assert_parity_raw(raw, True, name)

    def test_external_refs_and_unknown_format_fail_closed(self):
        schema = load_message_schema(SCHEMA_PATH)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external_ref = copy.deepcopy(schema)
            external_ref["$defs"]["short_text"] = {"$ref": "https://example.test/remote.schema.json"}
            external_path = root / "external-ref.json"
            external_path.write_text(json.dumps(external_ref), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_schema_message(valid_message(), external_path)

            unknown_format = copy.deepcopy(schema)
            unknown_format["properties"]["body"]["format"] = "trading-os-unknown-format"
            unknown_path = root / "unknown-format.json"
            unknown_path.write_text(json.dumps(unknown_format), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_schema_message(valid_message(), unknown_path)


if __name__ == "__main__":
    unittest.main()
