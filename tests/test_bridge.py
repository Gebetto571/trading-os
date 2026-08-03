import json
import tempfile
import unittest
import uuid
from pathlib import Path

from trading_os_bridge.store import Store


class StoreTests(unittest.TestCase):
    def test_duplicate_message_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "test.db"
            store = Store(database, Path(__file__).parents[1] / "migrations")
            store.migrate()
            message = {
                "schema_version": 1,
                "id": str(uuid.uuid4()),
                "created_at": "2026-08-02T12:00:00Z",
                "sender": "chatgpt",
                "recipient": "codex",
                "type": "task",
                "subject": "Test",
                "body": "Test body",
                "correlation_id": None,
                "artifacts": [],
                "metadata": {},
            }
            self.assertTrue(store.put_message(message, "inbound", "received"))
            self.assertFalse(store.put_message(message, "inbound", "received"))
            self.assertEqual(len(store.list_messages()), 1)
            self.assertEqual(store.get_message(message["id"])["status"], "received")
            self.assertIsNone(store.get_message(str(uuid.uuid4())))

    def test_migration_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "test.db", Path(__file__).parents[1] / "migrations")
            self.assertEqual(store.migrate(), 2)
            self.assertEqual(store.migrate(), 0)


if __name__ == "__main__":
    unittest.main()
