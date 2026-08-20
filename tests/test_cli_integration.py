import argparse
import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse
from unittest.mock import patch

from trading_os_bridge import cli


MIGRATIONS = Path(__file__).parents[1] / "migrations"


def message(message_id=None, body="body"):
    return {
        "schema_version": 1, "id": message_id or str(uuid.uuid4()),
        "created_at": "2026-08-03T12:00:00Z", "sender": "cloud-planner",
        "recipient": "codex-dev", "type": "task", "subject": "Test", "body": body,
        "correlation_id": None, "artifacts": [], "metadata": {},
    }


def chief_task(domain="00"):
    item = message()
    item.update(sender="chatgpt", recipient="codex-local")
    item["metadata"] = {
        "project_domain": domain,
        "cloud_conversation_key": f"tos-cloud-{domain}",
        "local_lane": f"chief-engineer/{domain}",
        "authority": "chief-engineer",
        "approval_state": "approved_for_local_implementation",
        "change_mode": "STANDARD",
        "implementation_brief": {
            "outcome": "Outcome", "approved_logic": ["Logic"], "in_scope": ["Scope"],
            "non_goals": ["Non-goal"], "acceptance_criteria": ["Criterion"],
            "required_tests": ["Test"], "risks": ["Risk"], "stop_conditions": ["Stop"],
        },
    }
    return item


def bound_chief_task(domain="00", paths=None, base_commit="abc123"):
    paths = paths or ["tests/exact_cli.py"]
    item = chief_task(domain)
    item["metadata"]["FROZEN_OWNED_PATHS"] = list(paths)
    item["metadata"]["SCOPE_BINDING_MANIFEST"] = {
        "active_writer_principal": "chief-engineer",
        "canonical_lane": f"chief-engineer/{domain}",
        "expected_base_commit": base_commit,
        "exact_owned_paths": list(paths),
    }
    return item


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.inbox = self.root / "inbox"
        self.archive = self.root / "archive"
        self.quarantine = self.root / "quarantine"
        self.outbox = self.root / "outbox"
        self.inbox.mkdir()
        self.patches = [
            patch.object(cli, "DEFAULT_DB", self.root / "bridge.db"),
            patch.object(cli, "MIGRATIONS", MIGRATIONS),
            patch.object(cli, "INBOX", self.inbox),
            patch.object(cli, "ARCHIVE", self.archive),
            patch.object(cli, "QUARANTINE", self.quarantine),
            patch.object(cli, "OUTBOX", self.outbox),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def _write(self, name, payload):
        path = self.inbox / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_relative_ingest_duplicate_conflict_and_quarantine(self):
        item = message()
        self._write("ok.json", item)
        old_cwd = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(cli.command_ingest(argparse.Namespace(path="inbox")), 0)
        finally:
            os.chdir(old_cwd)
        self.assertTrue((self.archive / "ok.json").exists())
        stored = cli.store().get_message(item["id"])
        self.assertEqual(stored["source_uri"], (self.archive / "ok.json").resolve().as_uri())
        self.assertEqual(stored["status"], "received")

        self._write("duplicate.json", item)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        self.assertTrue((self.archive / "duplicate.json").exists())

        self._write("conflict.json", dict(item, body="different"))
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 1)
        self.assertTrue((self.quarantine / "conflict.json").exists())

        (self.inbox / "invalid.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 1)
        self.assertTrue((self.quarantine / "invalid.json").exists())
        with cli.store().connect() as connection:
            events = list(connection.execute(
                "SELECT kind, message_id, quarantine_uri, raw_sha256 FROM quarantine_events ORDER BY id"
            ))
        self.assertEqual([row["kind"] for row in events], ["integrity_conflict", "invalid"])
        self.assertEqual(events[0]["message_id"], item["id"])
        self.assertTrue(events[0]["quarantine_uri"].startswith("file://"))
        self.assertEqual(len(events[0]["raw_sha256"]), 64)

    def test_archive_failure_leaves_source_and_no_claimable_ghost(self):
        item = message()
        source = self._write("move-fails.json", item)
        with patch.object(cli.os, "replace", side_effect=OSError("injected move failure")):
            self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 1)
        self.assertTrue(source.exists())
        self.assertIsNone(cli.store().get_message(item["id"]))
        self.assertIsNone(cli.store().claim_message("worker"))

    def test_crash_after_archive_before_activation_is_reconciled(self):
        item = message()
        raw = json.dumps(item).encode("utf-8")
        archived = self.archive / "pending.json"
        self.archive.mkdir()
        archived.write_bytes(raw)
        database = cli.store()
        database.put_message(item, "inbound", "queued", archived.resolve().as_uri(), raw)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        self.assertEqual(database.get_message(item["id"])["status"], "received")
        self.assertEqual(database.claim_message("worker")["id"], item["id"])

    def test_init_tightens_existing_work_directories(self):
        for path in (self.inbox, self.archive, self.quarantine, self.outbox):
            path.mkdir(exist_ok=True)
            os.chmod(path, 0o777)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(cli.command_init(argparse.Namespace()), 0)
        self.assertIn("Uygulanan yeni migration: 4", output.getvalue())
        for path in (self.inbox, self.archive, self.quarantine, self.outbox):
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)

    def test_cli_terminal_status_requires_current_worker_and_lease(self):
        item = message()
        database = cli.store()
        database.put_message(item, "inbound", "received")
        database.claim_message("owner", 30)
        base = {"id": item["id"], "status": "completed", "error": None}
        self.assertEqual(cli.command_status(argparse.Namespace(**base, worker=None)), 1)
        self.assertEqual(cli.command_status(argparse.Namespace(**base, worker="other")), 1)
        self.assertEqual(cli.command_status(argparse.Namespace(**base, worker="owner")), 0)

    def test_cli_status_parser_rejects_non_terminal_states(self):
        for status in ("queued", "received", "processing"):
            with self.subTest(status=status), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cli.parser().parse_args(["status", str(uuid.uuid4()), status])

    def test_ingest_rejects_outside_file_without_moving_it(self):
        outside = self.root / "outside.json"
        outside.write_text(json.dumps(message()), encoding="utf-8")
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(outside))), 1)
        self.assertTrue(outside.exists())
        self.assertFalse(self.archive.exists())
        self.assertFalse(self.quarantine.exists())

    def test_ingest_rejects_parent_symlink_escape(self):
        outside = self.root / "outside"
        outside.mkdir()
        payload = outside / "message.json"
        payload.write_text(json.dumps(message()), encoding="utf-8")
        link = self.inbox / "escape"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(link))), 1)
        self.assertTrue(payload.exists())
        self.assertTrue(link.is_symlink())

    def test_symlink_json_quarantine_does_not_chmod_external_target(self):
        outside = self.root / "external.json"
        outside.write_text(json.dumps(message()), encoding="utf-8")
        os.chmod(outside, 0o644)
        link = self.inbox / "linked.json"
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink unavailable")
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 1)
        self.assertEqual(os.stat(outside).st_mode & 0o777, 0o644)
        self.assertTrue((self.quarantine / "linked.json").is_symlink())

    def test_chief_engineer_claim_and_correlated_result_envelope(self):
        item = chief_task("00")
        self._write("task.json", item)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        self.assertTrue((self.archive / "task.json").exists())
        claim_args = argparse.Namespace(
            lane="chief-engineer/00", base_commit="abc123",
            owned_path=["trading_os_bridge", "schemas/message.schema.json"], lease_seconds=300,
        )
        self.assertEqual(cli.command_claim_task(claim_args), 0)
        report = {
            "subject": "Implemented",
            "body": "Local implementation verified.",
            "changed_files": ["trading_os_bridge/store.py"],
            "commands": [{"command": "python3 -m unittest", "exit_code": 0, "summary": "passed"}],
            "git_state": {"branch": "main", "commit_created": False},
            "skipped_checks": [],
            "risks": [],
            "verification_verdict": "ALIGNED",
            "next_safe_step": "Drive readback",
        }
        report_path = self.root / "result.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        self.assertEqual(cli.command_result(argparse.Namespace(
            task_id=item["id"], report=str(report_path)
        )), 0)
        task_row = cli.store().get_message(item["id"])
        self.assertIsNotNone(task_row["result_message_id"])
        result_row = cli.store().get_message(task_row["result_message_id"])
        result = json.loads(result_row["payload_json"])
        self.assertEqual(result["correlation_id"], item["id"])
        self.assertEqual(result["metadata"]["result"]["verification_verdict"], "ALIGNED")
        self.assertTrue(all(
            value is False
            for value in result["metadata"]["result"]["permission_state"].values()
        ))
        self.assertTrue(cli.store().update_status(item["id"], "completed", worker="chief-engineer"))

    def test_cli_exact_claim_only_targets_requested_uuid(self):
        first = bound_chief_task(paths=["tests/first_cli.py"])
        target = bound_chief_task(paths=["tests/target_cli.py"])
        self._write("first.json", first)
        self._write("target.json", target)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)

        args = cli.parser().parse_args([
            "claim-task", "--id", target["id"], "--lane", "chief-engineer/00",
            "--principal", "chief-engineer", "--base-commit", "abc123",
            "--owned-path", "tests/target_cli.py", "--lease-seconds", "30",
        ])
        self.assertEqual(args.func(args), 0)
        self.assertEqual(cli.store().get_message(target["id"])["status"], "processing")
        self.assertEqual(cli.store().get_message(first["id"])["status"], "received")

        missing = cli.parser().parse_args([
            "claim-task", "--id", str(uuid.uuid4()), "--lane", "chief-engineer/00",
            "--principal", "chief-engineer", "--base-commit", "abc123",
            "--owned-path", "tests/first_cli.py",
        ])
        self.assertEqual(missing.func(missing), 1)
        self.assertEqual(cli.store().get_message(first["id"])["status"], "received")

        blank = argparse.Namespace(
            id="", lane="chief-engineer/00", principal="chief-engineer", base_commit="abc123",
            owned_path=["tests/first_cli.py"], lease_seconds=30,
        )
        self.assertEqual(cli.command_claim_task(blank), 1)
        self.assertEqual(cli.store().get_message(first["id"])["status"], "received")

    def test_cli_exact_reclaim_renews_only_expired_target(self):
        item = bound_chief_task(paths=["tests/reclaim_cli.py"])
        self._write("reclaim.json", item)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        claim = argparse.Namespace(
            id=item["id"], lane="chief-engineer/00", principal="chief-engineer",
            base_commit="abc123", owned_path=["tests/reclaim_cli.py"], lease_seconds=30,
        )
        self.assertEqual(cli.command_claim_task(claim), 0)
        with cli.store().connect() as connection:
            connection.execute(
                "UPDATE messages SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (item["id"],)
            )
        reclaim = cli.parser().parse_args([
            "reclaim-task", "--id", item["id"], "--lane", "chief-engineer/00",
            "--principal", "chief-engineer", "--lease-seconds", "30",
        ])
        self.assertEqual(reclaim.func(reclaim), 0)
        self.assertEqual(cli.store().get_message(item["id"])["attempt_count"], 2)

    def test_result_rejects_expired_chief_lease_before_writing_outbox(self):
        item = chief_task("00")
        self._write("expired.json", item)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        claim_args = argparse.Namespace(
            lane="chief-engineer/00", base_commit="abc123",
            owned_path=["trading_os_bridge/store.py"], lease_seconds=30,
        )
        self.assertEqual(cli.command_claim_task(claim_args), 0)
        with cli.store().connect() as connection:
            connection.execute(
                "UPDATE messages SET lease_until='2000-01-01T00:00:00Z' WHERE id=?", (item["id"],)
            )
        report = {
            "subject": "Expired", "body": "Lease must be live.",
            "changed_files": [], "commands": [],
            "git_state": {"branch": "main", "commit_created": False},
            "skipped_checks": [], "risks": [], "verification_verdict": "BLOCKED",
            "next_safe_step": "Reclaim the exact task.",
        }
        report_path = self.root / "expired-result.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        self.assertEqual(cli.command_result(argparse.Namespace(
            task_id=item["id"], report=str(report_path)
        )), 1)
        self.assertIsNone(cli.store().get_message(item["id"])["result_message_id"])
        self.assertEqual(list(self.outbox.glob("*__response.json")), [])

    def test_result_link_failure_compensates_new_outbox_artifact(self):
        item = chief_task("00")
        self._write("link-failure.json", item)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        claim_args = argparse.Namespace(
            lane="chief-engineer/00", base_commit="abc123",
            owned_path=["trading_os_bridge/store.py"], lease_seconds=30,
        )
        self.assertEqual(cli.command_claim_task(claim_args), 0)
        report = {
            "subject": "Link failure", "body": "Compensate unlinked output.",
            "changed_files": [], "commands": [],
            "git_state": {"branch": "main", "commit_created": False},
            "skipped_checks": [], "risks": [], "verification_verdict": "CONDITIONAL",
            "next_safe_step": "Retry only with a live lease.",
        }
        report_path = self.root / "link-failure-result.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        database = cli.store()
        with patch.object(cli, "store", return_value=database), patch.object(
            database, "link_result", return_value=False,
        ):
            self.assertEqual(cli.command_result(argparse.Namespace(
                task_id=item["id"], report=str(report_path)
            )), 1)
        result_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"trading-os-result:{item['id']}"))
        self.assertIsNone(database.get_message(result_id))
        self.assertEqual(list(self.outbox.glob("*__response.json")), [])

    def test_concurrent_deterministic_result_retries_preserve_linked_artifact(self):
        item = chief_task("00")
        self._write("concurrent-result.json", item)
        self.assertEqual(cli.command_ingest(argparse.Namespace(path=str(self.inbox))), 0)
        claim_args = argparse.Namespace(
            lane="chief-engineer/00", base_commit="abc123",
            owned_path=["trading_os_bridge/store.py"], lease_seconds=30,
        )
        self.assertEqual(cli.command_claim_task(claim_args), 0)
        report = {
            "subject": "Concurrent result", "body": "One immutable artifact survives retries.",
            "changed_files": [], "commands": [],
            "git_state": {"branch": "main", "commit_created": False},
            "skipped_checks": [], "risks": [], "verification_verdict": "ALIGNED",
            "next_safe_step": "Drive readback",
        }
        report_path = self.root / "concurrent-result-report.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        database = cli.store()
        start = threading.Barrier(3)
        put_barrier = threading.Barrier(2)
        results = []
        original_put = database.put_message

        def raced_put(*args, **kwargs):
            put_barrier.wait(timeout=5)
            return original_put(*args, **kwargs)

        def produce_result():
            start.wait(timeout=5)
            results.append(cli.command_result(argparse.Namespace(
                task_id=item["id"], report=str(report_path)
            )))

        with patch.object(cli, "store", return_value=database), patch.object(
            cli, "now_utc", return_value="2026-08-20T15:30:00Z",
        ), patch.object(database, "put_message", side_effect=raced_put):
            threads = [threading.Thread(target=produce_result) for _ in range(2)]
            for thread in threads:
                thread.start()
            start.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=5)

        self.assertEqual(sorted(results), [0, 0])
        task = database.get_message(item["id"])
        self.assertIsNotNone(task["result_message_id"])
        result = database.get_message(task["result_message_id"])
        artifact = Path(unquote(urlparse(result["source_uri"]).path))
        self.assertTrue(artifact.is_file())
        self.assertEqual(len(list(self.outbox.glob("*__response.json"))), 1)

    def test_existing_send_command_still_generates_a_valid_outbound_message(self):
        args = argparse.Namespace(
            to="cloud-planner", type="task", subject="Regression", body="Body",
            correlation_id=None,
        )
        self.assertEqual(cli.command_send(args), 0)
        files = list(self.outbox.glob("*.json"))
        self.assertEqual(len(files), 1)
        payload = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["recipient"], "cloud-planner")
        self.assertEqual(cli.store().get_message(payload["id"])["direction"], "outbound")


if __name__ == "__main__":
    unittest.main()
