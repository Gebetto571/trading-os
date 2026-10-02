import json
import sqlite3
import shutil
import tempfile
import threading
import unittest
import uuid
import os
from pathlib import Path

from trading_os_bridge.store import (
    DISPOSABLE_MARKER, DISPOSABLE_MARKER_CONTENT, DisposableMigrationRequired,
    IntegrityConflict, InvalidTransition, NotReversibleMigration, OwnershipConflict, Store,
)


MIGRATIONS = Path(__file__).parents[1] / "migrations"


def message(message_id=None, body="body"):
    return {
        "schema_version": 1, "id": message_id or str(uuid.uuid4()),
        "created_at": "2026-08-03T12:00:00Z", "sender": "cloud-planner",
        "recipient": "codex-dev", "type": "task", "subject": "Test", "body": body,
        "correlation_id": None, "artifacts": [], "metadata": {},
    }


def chief_task(domain="00", message_id=None):
    item = message(message_id)
    item.update(sender="chatgpt", recipient="codex-local")
    item["metadata"] = {
        "project_domain": domain,
        "cloud_conversation_key": f"tos-cloud-{domain}",
        "local_lane": f"chief-engineer/{domain}",
        "authority": "chief-engineer",
        "approval_state": "approved_for_local_implementation",
        "change_mode": "STANDARD",
        "implementation_brief": {},
    }
    return item


def bound_chief_task(domain="00", paths=None, base_commit="abc123", message_id=None):
    paths = paths or ["tests/exact_claim.py"]
    item = chief_task(domain, message_id)
    item["metadata"]["FROZEN_OWNED_PATHS"] = list(paths)
    item["metadata"]["SCOPE_BINDING_MANIFEST"] = {
        "active_writer_principal": "chief-engineer",
        "canonical_lane": f"chief-engineer/{domain}",
        "expected_base_commit": base_commit,
        "exact_owned_paths": list(paths),
    }
    return item


class StoreHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "test.db", MIGRATIONS)
        self.store.migrate()

    def tearDown(self):
        self.temp.cleanup()

    def disposable_store(self, migrations=MIGRATIONS):
        root = Path(tempfile.mkdtemp(dir=self.temp.name, prefix="trading-os-disposable-"))
        (root / DISPOSABLE_MARKER).write_text(DISPOSABLE_MARKER_CONTENT, encoding="utf-8")
        return Store(root / "fixture.db", migrations)

    @staticmethod
    def migration_snapshot(store):
        with store.connect() as connection:
            schema = [tuple(row) for row in connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            )]
            versions = [row[0] for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            )]
        return {"schema": schema, "versions": versions}

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

    def test_chief_engineer_claim_is_lane_scoped_and_restart_idempotent(self):
        item = chief_task("04")
        self.store.put_message(item, "inbound", "received")
        self.assertIsNone(self.store.claim_chief_engineer_task(
            "chief-engineer/03", "abc123", ["tests/test_bridge.py"]
        ))
        claimed = self.store.claim_chief_engineer_task(
            "chief-engineer/04", "abc123", ["tests/test_bridge.py"]
        )
        self.assertEqual(claimed["id"], item["id"])
        self.assertEqual(claimed["active_writer"], "chief-engineer")
        self.assertEqual(json.loads(claimed["owned_paths_json"]), ["tests/test_bridge.py"])
        restarted = Store(self.store.database, MIGRATIONS)
        restarted.migrate()
        self.assertIsNone(restarted.claim_chief_engineer_task(
            "chief-engineer/04", "abc123", ["tests/test_bridge.py"]
        ))
        self.assertEqual(restarted.get_message(item["id"])["attempt_count"], 1)

    def test_chief_engineer_claim_rejects_unapproved_and_overlapping_paths(self):
        invalid = chief_task("00")
        invalid["metadata"]["approval_state"] = "draft"
        self.store.put_message(invalid, "inbound", "received")
        self.assertIsNone(self.store.claim_message("not-chief-engineer"))
        self.assertIsNone(self.store.claim_chief_engineer_task(
            "chief-engineer/00", "abc123", ["trading_os_bridge/store.py"]
        ))

        first = chief_task("01")
        second = chief_task("02")
        self.store.put_message(first, "inbound", "received")
        self.store.put_message(second, "inbound", "received")
        self.store.claim_chief_engineer_task(
            "chief-engineer/01", "abc123", ["trading_os_bridge"]
        )
        with self.assertRaises(OwnershipConflict) as context:
            self.store.claim_chief_engineer_task(
                "chief-engineer/02", "abc123", ["trading_os_bridge/cli.py"]
            )
        self.assertIn("çakışıyor", str(context.exception))

    def test_chief_engineer_owned_paths_are_repository_relative_and_non_overlapping(self):
        for paths in (["/tmp/x"], ["../secret"], ["schemas", "schemas/message.schema.json"]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.store.claim_chief_engineer_task("chief-engineer/00", "abc123", paths)

    def test_exact_chief_claim_changes_only_the_requested_received_task(self):
        first = bound_chief_task(paths=["tests/first.py"])
        target = bound_chief_task(paths=["tests/target.py"])
        self.store.put_message(first, "inbound", "received")
        self.store.put_message(target, "inbound", "received")

        claimed = self.store.claim_chief_engineer_task_by_id(
            target["id"], "chief-engineer/00", "abc123", ["tests/target.py"], 30,
        )

        self.assertEqual(claimed["id"], target["id"])
        self.assertEqual(self.store.get_message(first["id"])["status"], "received")
        self.assertEqual(self.store.get_message(first["id"])["attempt_count"], 0)
        self.assertEqual(self.store.get_message(target["id"])["attempt_count"], 1)

    def test_exact_chief_claim_rejects_bad_identity_or_binding_without_delta(self):
        item = bound_chief_task(paths=["tests/bound.py"])
        unbound = chief_task()
        self.store.put_message(item, "inbound", "received")
        self.store.put_message(unbound, "inbound", "received")
        before = dict(self.store.get_message(item["id"]))

        self.assertIsNone(self.store.claim_chief_engineer_task_by_id(
            str(uuid.uuid4()), "chief-engineer/00", "abc123", ["tests/bound.py"], 30,
        ))
        for lane, principal, base, paths in (
            ("chief-engineer/01", "chief-engineer", "abc123", ["tests/bound.py"]),
            ("chief-engineer/00", "not-chief", "abc123", ["tests/bound.py"]),
            ("chief-engineer/00", "chief-engineer", "different", ["tests/bound.py"]),
            ("chief-engineer/00", "chief-engineer", "abc123", ["tests/other.py"]),
        ):
            with self.subTest(lane=lane, principal=principal, base=base, paths=paths):
                with self.assertRaises(InvalidTransition):
                    self.store.claim_chief_engineer_task_by_id(
                        item["id"], lane, base, paths, 30, principal,
                    )
                after = self.store.get_message(item["id"])
                self.assertEqual(after["status"], before["status"])
                self.assertEqual(after["revision"], before["revision"])
                self.assertEqual(after["attempt_count"], before["attempt_count"])
        with self.assertRaises(InvalidTransition):
            self.store.claim_chief_engineer_task_by_id(
                unbound["id"], "chief-engineer/00", "abc123", ["tests/exact_claim.py"], 30,
            )
        self.assertEqual(self.store.get_message(unbound["id"])["status"], "received")

        self.store.claim_chief_engineer_task_by_id(
            item["id"], "chief-engineer/00", "abc123", ["tests/bound.py"], 30,
        )
        with self.assertRaises(InvalidTransition):
            self.store.claim_chief_engineer_task_by_id(
                item["id"], "chief-engineer/00", "abc123", ["tests/bound.py"], 30,
            )

    def test_exact_chief_claim_rejects_malformed_frozen_path_list_without_delta(self):
        item = bound_chief_task(paths=["a", "b"])
        item["metadata"]["FROZEN_OWNED_PATHS"] = "ab"
        item["metadata"]["SCOPE_BINDING_MANIFEST"]["exact_owned_paths"] = "ab"
        self.store.put_message(item, "inbound", "received")
        before = dict(self.store.get_message(item["id"]))

        with self.assertRaises(InvalidTransition):
            self.store.claim_chief_engineer_task_by_id(
                item["id"], "chief-engineer/00", "abc123", ["a", "b"], 30,
            )

        after = self.store.get_message(item["id"])
        self.assertEqual(after["status"], before["status"])
        self.assertEqual(after["revision"], before["revision"])
        self.assertEqual(after["attempt_count"], before["attempt_count"])
        self.store.update_status(item["id"], "failed", worker="chief-engineer")
        with self.assertRaises(InvalidTransition):
            self.store.claim_chief_engineer_task_by_id(
                item["id"], "chief-engineer/00", "abc123", ["tests/bound.py"], 30,
            )

    def test_exact_chief_claim_blocks_second_mutating_writer_but_not_outbox_probe(self):
        active = bound_chief_task(paths=["trading_os_bridge/store.py"])
        read_only = bound_chief_task(paths=["var/outbox"])
        read_only_overlap = bound_chief_task(paths=["var/outbox"])
        second = bound_chief_task(paths=["tests/second.py"])
        for item in (active, read_only, read_only_overlap, second):
            self.store.put_message(item, "inbound", "received")

        self.store.claim_chief_engineer_task_by_id(
            active["id"], "chief-engineer/00", "abc123", ["trading_os_bridge/store.py"], 30,
        )
        probe = self.store.claim_chief_engineer_task_by_id(
            read_only["id"], "chief-engineer/00", "abc123", ["var/outbox"], 30,
        )
        self.assertEqual(probe["id"], read_only["id"])
        with self.assertRaises(OwnershipConflict):
            self.store.claim_chief_engineer_task_by_id(
                read_only_overlap["id"], "chief-engineer/00", "abc123", ["var/outbox"], 30,
            )
        with self.assertRaises(OwnershipConflict):
            self.store.claim_chief_engineer_task_by_id(
                second["id"], "chief-engineer/00", "abc123", ["tests/second.py"], 30,
            )
        self.assertEqual(self.store.get_message(second["id"])["status"], "received")

    def test_exact_chief_claim_race_has_one_winner(self):
        item = bound_chief_task(paths=["tests/race.py"])
        self.store.put_message(item, "inbound", "received")
        barrier = threading.Barrier(3)
        results = []

        def claim():
            barrier.wait()
            try:
                results.append(self.store.claim_chief_engineer_task_by_id(
                    item["id"], "chief-engineer/00", "abc123", ["tests/race.py"], 30,
                ))
            except InvalidTransition:
                results.append(None)

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(row is not None for row in results), 1)
        self.assertEqual(self.store.get_message(item["id"])["attempt_count"], 1)

    def test_exact_expired_reclaim_is_cas_and_preserves_binding(self):
        item = bound_chief_task(paths=["tests/reclaim.py"])
        self.store.put_message(item, "inbound", "received")
        claimed = self.store.claim_chief_engineer_task_by_id(
            item["id"], "chief-engineer/00", "abc123", ["tests/reclaim.py"], 30,
        )
        with self.store.connect() as connection:
            connection.execute(
                "UPDATE messages SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (item["id"],)
            )
        self.assertEqual(self.store.recover_expired(), 0)
        with self.assertRaises(InvalidTransition):
            self.store.recover_message(item["id"])
        original_paths = claimed["owned_paths_json"]
        original_base = claimed["base_commit"]
        barrier = threading.Barrier(3)
        results = []

        def reclaim():
            barrier.wait()
            try:
                results.append(self.store.reclaim_chief_engineer_task_by_id(
                    item["id"], "chief-engineer/00", 30,
                ))
            except InvalidTransition:
                results.append(None)

        threads = [threading.Thread(target=reclaim) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(row is not None for row in results), 1)
        reclaimed = self.store.get_message(item["id"])
        self.assertEqual(reclaimed["attempt_count"], 2)
        self.assertEqual(reclaimed["base_commit"], original_base)
        self.assertEqual(reclaimed["owned_paths_json"], original_paths)
        with self.assertRaises(InvalidTransition):
            self.store.reclaim_chief_engineer_task_by_id(item["id"], "chief-engineer/00", 30)

    def test_legacy_claim_rejects_frozen_task_and_chief_completion_requires_result(self):
        frozen = bound_chief_task("01", paths=["tests/frozen.py"])
        self.store.put_message(frozen, "inbound", "received")
        with self.assertRaises(InvalidTransition):
            self.store.claim_chief_engineer_task(
                "chief-engineer/01", "abc123", ["tests/frozen.py"], 30,
            )
        self.assertEqual(self.store.get_message(frozen["id"])["status"], "received")

        legacy = chief_task()
        self.store.put_message(legacy, "inbound", "received")
        self.store.claim_chief_engineer_task(
            "chief-engineer/00", "abc123", ["tests/legacy.py"], 30,
        )
        with self.assertRaises(InvalidTransition):
            self.store.update_status(legacy["id"], "completed", worker="chief-engineer")

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

    def test_disposable_down_migration_reverts_only_explicit_version_and_is_retryable(self):
        first_three = Path(self.temp.name) / "migrations-v3"
        first_three.mkdir()
        for source in MIGRATIONS.glob("00[1-3]_*.sql"):
            shutil.copyfile(source, first_three / source.name)
        candidate = self.disposable_store(first_three)
        self.assertEqual(candidate.migrate(), 3)
        before = self.migration_snapshot(candidate)

        upgraded = Store(candidate.database, MIGRATIONS)
        self.assertEqual(upgraded.migrate(), 1)
        self.assertEqual(upgraded.migrate_down_disposable(3), 1)
        self.assertEqual(self.migration_snapshot(upgraded), before)

        self.assertEqual(upgraded.migrate(), 1)
        with upgraded.connect() as connection:
            connection.execute(
                """CREATE TRIGGER reject_revision_drop BEFORE DELETE ON schema_migrations
                   WHEN OLD.version=4 BEGIN SELECT RAISE(ABORT, 'fixture guard'); END"""
            )
        guarded_before = self.migration_snapshot(upgraded)
        with self.assertRaises(sqlite3.DatabaseError):
            upgraded.migrate_down_disposable(3)
        self.assertEqual(self.migration_snapshot(upgraded), guarded_before)
        with upgraded.connect() as connection:
            connection.execute("DROP TRIGGER reject_revision_drop")
        self.assertEqual(upgraded.migrate_down_disposable(3), 1)
        self.assertEqual(self.migration_snapshot(upgraded), before)

    def test_down_migration_rejects_non_disposable_or_unsupported_target_without_mutation(self):
        before = self.migration_snapshot(self.store)
        with self.assertRaises(DisposableMigrationRequired):
            self.store.migrate_down_disposable(3)
        self.assertEqual(self.migration_snapshot(self.store), before)

        candidate = self.disposable_store()
        self.assertEqual(candidate.migrate(), 4)
        disposable_before = self.migration_snapshot(candidate)
        with self.assertRaises(NotReversibleMigration):
            candidate.migrate_down_disposable(2)
        self.assertEqual(self.migration_snapshot(candidate), disposable_before)

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
        self.assertEqual(upgraded.migrate(), 3)
        self.assertEqual(upgraded.get_decision("DEC-OLD", 1)["body"], "preserved")
        self.assertEqual(upgraded.put_decision("DEC-OLD", "Old", "accepted", "v2"), 2)


if __name__ == "__main__":
    unittest.main()
