import json
import shutil
import tempfile
import threading
import unittest
import uuid
import os
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
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "failed", "boom")
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "failed", "boom", "other-worker")
        self.assertTrue(self.store.update_status(item["id"], "failed", "boom", "worker"))
        terminal = self.store.get_message(item["id"])
        self.assertEqual(terminal["terminal_by"], "worker")
        self.assertIsNotNone(terminal["terminal_at"])
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "failed", "again", "worker")
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "received")
        self.assertTrue(self.store.recover_message(item["id"], "user requested"))
        recovered = self.store.get_message(item["id"])
        self.assertEqual(recovered["status"], "received")
        self.assertIsNone(recovered["terminal_by"])
        self.assertIsNone(recovered["terminal_at"])
        with self.assertRaises(InvalidTransition):
            self.store.recover_message(item["id"])
        self.assertEqual(self.store.claim_message("worker", 30)["id"], item["id"])
        self.store.update_status(item["id"], "completed", worker="worker")

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

    def test_inbound_processing_cannot_bypass_claim(self):
        received = message()
        self.store.put_message(received, "inbound", "received")
        with self.assertRaises(InvalidTransition):
            self.store.update_status(received["id"], "processing")
        queued = message()
        self.store.put_message(queued, "inbound", "queued")
        with self.assertRaises(InvalidTransition):
            self.store.update_status(queued["id"], "processing")
        outbound = message()
        self.store.put_message(outbound, "outbound", "queued")
        self.assertTrue(self.store.update_status(outbound["id"], "processing"))

    def test_terminal_write_race_has_single_winner(self):
        item = message()
        self.store.put_message(item, "inbound", "received")
        self.store.claim_message("owner", 30)
        barrier = threading.Barrier(3)
        results = []

        def finish(status):
            barrier.wait()
            try:
                results.append(self.store.update_status(item["id"], status, worker="owner"))
            except InvalidTransition:
                results.append(False)

        threads = [threading.Thread(target=finish, args=(status,)) for status in ("completed", "failed")]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    def test_expired_lease_cannot_finish(self):
        item = message()
        self.store.put_message(item, "inbound", "received")
        self.store.claim_message("owner", 30)
        with self.store.connect() as connection:
            connection.execute("UPDATE messages SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (item["id"],))
        with self.assertRaises(InvalidTransition):
            self.store.update_status(item["id"], "completed", worker="owner")

    def test_outbound_failed_message_cannot_enter_inbound_recovery(self):
        item = message()
        self.store.put_message(item, "outbound", "queued")
        self.assertTrue(self.store.update_status(item["id"], "failed"))
        with self.assertRaises(InvalidTransition):
            self.store.recover_message(item["id"])

    def test_database_permissions_and_shared_parent_are_safe(self):
        shared = Path(self.temp.name) / "shared"
        shared.mkdir(mode=0o755)
        os.chmod(shared, 0o755)
        database = shared / "permissions.db"
        secured = Store(database, MIGRATIONS)
        secured.migrate()
        connection = secured.connect()
        try:
            connection.execute("INSERT INTO sync_runs(started_at,direction,status) VALUES('x','pull','running')")
            connection.commit()
            for suffix in ("", "-wal", "-shm"):
                path = Path(str(database) + suffix)
                if path.exists():
                    os.chmod(path, 0o666)
            with secured.connect():
                pass
            self.assertEqual(os.stat(shared).st_mode & 0o777, 0o755)
            self.assertEqual(os.stat(database).st_mode & 0o777, 0o600)
            for suffix in ("-wal", "-shm"):
                path = Path(str(database) + suffix)
                if path.exists():
                    self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        finally:
            connection.close()

    def test_new_database_and_first_wal_files_are_private(self):
        database = Path(self.temp.name) / "first-use" / "new.db"
        secured = Store(database, MIGRATIONS)
        secured.migrate()
        connection = secured.connect()
        try:
            connection.execute("INSERT INTO sync_runs(started_at,direction,status) VALUES('x','pull','running')")
            connection.commit()
            for suffix in ("", "-wal", "-shm"):
                path = Path(str(database) + suffix)
                if path.exists():
                    self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        finally:
            connection.close()

    def test_failed_migration_is_fully_rollbackable_and_retryable(self):
        migration_dir = Path(self.temp.name) / "atomic-migrations"
        migration_dir.mkdir()
        for source in MIGRATIONS.glob("00[1-3]_*.sql"):
            shutil.copyfile(source, migration_dir / source.name)
        broken = migration_dir / "004_injected.sql"
        broken.write_text("CREATE TABLE partial_change(id INTEGER);\nSELECT * FROM no_such_table;\n", encoding="utf-8")
        database = Path(self.temp.name) / "atomic.db"
        candidate = Store(database, migration_dir)
        with self.assertRaises(Exception):
            candidate.migrate()
        with candidate.connect() as connection:
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='partial_change'"
            ).fetchone())
            self.assertIsNone(connection.execute(
                "SELECT version FROM schema_migrations WHERE version=4"
            ).fetchone())
        broken.write_text("CREATE TABLE repaired_change(id INTEGER);\n", encoding="utf-8")
        self.assertEqual(candidate.migrate(), 1)
        with candidate.connect() as connection:
            self.assertIsNotNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='repaired_change'"
            ).fetchone())
            self.assertIsNotNone(connection.execute(
                "SELECT version FROM schema_migrations WHERE version=4"
            ).fetchone())

        record_failure = migration_dir / "005_record_failure.sql"
        record_failure.write_text("CREATE TABLE record_coupled_change(id INTEGER);\n", encoding="utf-8")
        with candidate.connect() as connection:
            connection.execute(
                """CREATE TRIGGER reject_migration_5 BEFORE INSERT ON schema_migrations
                   WHEN NEW.version=5 BEGIN SELECT RAISE(ABORT, 'injected record failure'); END"""
            )
        with self.assertRaises(Exception):
            candidate.migrate()
        with candidate.connect() as connection:
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='record_coupled_change'"
            ).fetchone())
            self.assertIsNone(connection.execute(
                "SELECT version FROM schema_migrations WHERE version=5"
            ).fetchone())
            connection.execute("DROP TRIGGER reject_migration_5")
        self.assertEqual(candidate.migrate(), 1)

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
        self.assertEqual(upgraded.migrate(), 2)
        self.assertEqual(upgraded.get_decision("DEC-OLD", 1)["body"], "preserved")
        self.assertEqual(upgraded.put_decision("DEC-OLD", "Old", "accepted", "v2"), 2)


if __name__ == "__main__":
    unittest.main()
