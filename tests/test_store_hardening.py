import json
import shutil
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from trading_os_bridge.store import IntegrityConflict, InvalidTransition, Store


MIGRATIONS = Path(__file__).parents[1] / "migrations"


def message(message_id=None, body="body"):
    return {
        "schema_version": 1, "id": message_id or str(uuid.uuid4()),
        "created_at": "2026-08-03T12:00:00Z", "sender": "cloud-planner",
        "recipient": "codex-dev", "type": "task", "subject": "Test", "body": body,
        "correlation_id": None, "artifacts": [], "metadata": {},
    }


class StoreHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.db", MIGRATIONS)
        self.store.migrate()

    def tearDown(self):
        self.temp.cleanup()

    def test_duplicate_and_integrity_conflict(self):
        original = message()
        raw = json.dumps(original, indent=2).encode()
        self.assertTrue(self.store.put_message(original, "inbound", "received", raw_payload=raw))
        self.assertFalse(self.store.put_message(dict(reversed(list(original.items()))), "inbound", "received"))
        changed = dict(original, body="changed")
        with self.assertRaises(IntegrityConflict):
            self.store.put_message(changed, "inbound", "received")
        row = self.store.get_message(original["id"])
        self.assertEqual(len(row["payload_sha256"]), 64)
        self.assertEqual(len(row["raw_sha256"]), 64)

    def test_transitions_and_explicit_recovery(self):
        item = message()
        self.store.put_message(item, "inbound", "received")
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "completed")
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "processing")
        claimed = self.store.claim_message("worker", 30)
        self.assertEqual(claimed["status"], "processing")
        self.assertTrue(self.store.update_status(item["id"], "failed", "boom"))
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "received")
        self.assertTrue(self.store.recover_message(item["id"], "user requested"))
        self.assertEqual(self.store.get_message(item["id"])["status"], "received")
        with self.assertRaises(InvalidTransition):
            self.store.recover_message(item["id"])
        self.assertEqual(self.store.claim_message("worker", 30)["id"], item["id"])
        self.store.update_status(item["id"], "completed")

        second = message()
        self.store.put_message(second, "inbound", "received")
        self.store.claim_message("worker", 30)
        with self.store.connect() as connection:
            connection.execute("UPDATE messages SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (second["id"],))
        self.assertEqual(self.store.recover_expired(), 1)
        self.assertEqual(self.store.get_message(second["id"])["status"], "received")

    def test_atomic_claim_race(self):
        item = message()
        self.store.put_message(item, "inbound", "received")
        barrier = threading.Barrier(3)
        results = []

        def claim(worker):
            barrier.wait()
            results.append(self.store.claim_message(worker, 30))

        threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(row is not None for row in results), 1)
        self.assertEqual(self.store.get_message(item["id"])["attempt_count"], 1)

    def test_decision_versions(self):
        self.assertEqual(self.store.put_decision("DEC-X", "Title", "proposed", "v1"), 1)
        self.assertEqual(self.store.put_decision("DEC-X", "Title", "accepted", "v2"), 2)
        self.assertEqual(self.store.get_decision("DEC-X")["body"], "v2")
        self.assertEqual(self.store.get_decision("DEC-X", 1)["body"], "v1")
        with self.assertRaises(IntegrityConflict):
            self.store.put_decision("DEC-X", "Title", "accepted", "bad", version=2)

    def test_migration_preserves_existing_decision_and_enables_v2(self):
        database = Path(self.temp.name) / "upgrade.db"
        first_dir = Path(self.temp.name) / "migrations-v1"
        first_dir.mkdir()
        shutil.copyfile(MIGRATIONS / "001_initial.sql", first_dir / "001_initial.sql")
        old_store = Store(database, first_dir)
        old_store.migrate()
        with old_store.connect() as connection:
            connection.execute(
                "INSERT INTO decisions(id,title,status,version,body,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                ("DEC-OLD", "Old", "accepted", 1, "preserved", "2026-08-03T00:00:00Z", "2026-08-03T00:00:00Z"),
            )
        upgraded = Store(database, MIGRATIONS)
        self.assertEqual(upgraded.migrate(), 1)
        self.assertEqual(upgraded.get_decision("DEC-OLD", 1)["body"], "preserved")
        self.assertEqual(upgraded.put_decision("DEC-OLD", "Old", "accepted", "v2"), 2)


if __name__ == "__main__":
    unittest.main()
