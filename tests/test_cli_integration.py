import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
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
