import copy
import unittest
import uuid
from pathlib import Path

from trading_os_bridge.validation import (
    canonical_bytes, load_conversation_map, parse_json_strict, sha256_bytes, validate_message,
)


CONVERSATION_MAP = load_conversation_map(
    Path(__file__).parents[1] / "schemas/conversation-map.json"
)


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


if __name__ == "__main__":
    unittest.main()
