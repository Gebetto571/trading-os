import copy
import unittest
import uuid

from trading_os_bridge.validation import canonical_bytes, parse_json_strict, sha256_bytes, validate_message


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


if __name__ == "__main__":
    unittest.main()
