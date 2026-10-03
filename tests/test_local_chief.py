"""Disposable Git/SQLite end-to-end checks for the explicit health-only worker."""

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from trading_os_bridge.store import Store
from trading_os_bridge.validation import canonical_bytes, sha256_bytes

SOURCE = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("local_chief", SOURCE / "scripts/local-chief.py")
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class LocalChiefTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.inbox = self.root / "var/inbox"
        self.outbox = self.root / "var/outbox"
        for path in (self.root / "var", self.inbox, self.outbox):
            path.mkdir(mode=0o700)
        self.database = Store(self.root / "var/bridge.db", SOURCE / "migrations")
        self.database.migrate()
        (self.root / ".gitignore").write_text("var/\nresearch/engine/.venv/\n")
        self.checker = self.root / "scripts/check-system.py"
        self.checker.parent.mkdir()
        python = self.root / "research/engine/.venv/bin/python"
        python.parent.mkdir(parents=True)
        python.symlink_to(sys.executable)
        self.write_checker()
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Worker Fixture")
        self.git("add", ".")
        self.git("commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.root_patch = patch.object(worker, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.temporary.cleanup)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, text=True,
                              capture_output=True, check=True).stdout

    def write_checker(self, healthy=True, suffix="", stdout_record=None):
        record = stdout_record or {
            "schema_version": 1, "verdict": "PASS" if healthy else "FAIL",
            "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "checks": [{"name": name, "ok": healthy} for name in sorted(worker.CHECK_NAMES)],
            "private_extra": "fixture-hidden-value",
        }
        code = ("import pathlib,sys\n"
                "root=pathlib.Path(__file__).resolve().parents[1]\n"
                "marker=root/'var/health-call-count'\n"
                "marker.write_text(str(int(marker.read_text())+1) if marker.exists() else '1')\n"
                "print('fixture-hidden-stderr',file=sys.stderr)\n"
                + suffix + "\n"
                + "print(" + repr(json.dumps(record)) + ")\n"
                + "raise SystemExit(" + str(0 if healthy else 1) + ")\n")
        self.checker.write_text(code)
        self.checker.chmod(0o600)

    def commit_checker(self):
        self.git("add", ".")
        self.git("commit", "-qm", "checker fixture")
        self.head = self.git("rev-parse", "HEAD").strip()

    def task(self, action="health", paths=None, body="Health status only."):
        paths = paths or ["var/outbox"]
        item = {
            "schema_version": 1, "id": str(uuid.uuid4()), "created_at": "2026-10-04T00:00:00Z",
            "sender": "chatgpt", "recipient": "codex-local", "type": "task",
            "subject": "Reviewed health", "body": body, "correlation_id": str(uuid.uuid4()),
            "artifacts": [], "metadata": {
                "project_domain": "00", "cloud_conversation_key": "tos-cloud-00",
                "local_lane": "chief-engineer/00", "authority": "chief-engineer",
                "approval_state": "approved_for_local_implementation", "change_mode": "STANDARD",
                "local_action": action, "FROZEN_OWNED_PATHS": paths,
                "SCOPE_BINDING_MANIFEST": {"active_writer_principal": "chief-engineer",
                    "canonical_lane": "chief-engineer/00", "expected_base_commit": self.head,
                    "exact_owned_paths": paths},
                "implementation_brief": {
                    "outcome": "Health status", "approved_logic": ["Read health"],
                    "in_scope": ["Health"], "non_goals": ["Trading"],
                    "acceptance_criteria": ["Correlated result"],
                    "required_tests": ["touch var/never-execute-required-tests"],
                    "risks": [], "stop_conditions": ["Wrong task hash"],
                },
            },
        }
        raw = canonical_bytes(item)
        self.database.put_message(item, "inbound", "received", (self.inbox / (item["id"] + ".json")).as_uri(), raw)
        return item, sha256_bytes(raw)

    def run_task(self, item, digest, extra=None):
        arguments = ["--task-id", item["id"], "--reviewed-sha256", digest,
                     "--repo", str(self.root), "--db", str(self.database.database),
                     "--inbox", str(self.inbox), "--outbox", str(self.outbox)]
        if extra:
            arguments.extend(extra)
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            status = worker.main(arguments)
        return status, json.loads(output.getvalue())

    def result_payload(self, response):
        return json.loads(Path(response["result_path"]).read_text())

    def test_health_exact_claim_correlated_sanitized_result_and_unchanged_checkout(self):
        item, digest = self.task()
        other, _ = self.task()
        before = worker.snapshot(self.root)
        status, response = self.run_task(item, digest)
        self.assertEqual(status, 0, response)
        self.assertFalse(response["duplicate"])
        result = self.result_payload(response)
        self.assertEqual(result["correlation_id"], item["correlation_id"])
        self.assertEqual(result["metadata"]["result"]["verification_verdict"], "ALIGNED")
        self.assertTrue(result["metadata"]["result"]["git_state"]["checkout_unchanged"])
        self.assertEqual(self.database.get_message(item["id"])["status"], "completed")
        self.assertEqual(self.database.get_message(other["id"])["status"], "received")
        self.assertEqual(before, worker.snapshot(self.root))
        self.assertEqual(Path(response["result_path"]).stat().st_mode & 0o777, 0o600)
        serialized = json.dumps(result)
        self.assertNotIn("fixture-hidden-value", serialized)
        self.assertNotIn("fixture-hidden-stderr", serialized)
        self.assertFalse(any(result["metadata"]["result"]["permission_state"].values()))
        self.assertFalse(list(self.outbox.glob(".local-chief-*")))

    def test_cloud_body_and_required_tests_never_execute(self):
        item, digest = self.task(body="$(touch var/never-execute-body); bash -c 'touch var/never-execute-body'")
        status, response = self.run_task(item, digest)
        self.assertEqual(status, 0, response)
        self.assertFalse((self.root / "var/never-execute-body").exists())
        self.assertFalse((self.root / "var/never-execute-required-tests").exists())
        self.assertNotIn(item["body"], json.dumps(self.result_payload(response)))

    def test_duplicate_reuses_immutable_result_without_second_health_process(self):
        item, digest = self.task()
        _, first = self.run_task(item, digest)
        status, second = self.run_task(item, digest)
        self.assertEqual(status, 0, second)
        self.assertTrue(second["duplicate"])
        self.assertEqual(first["result_id"], second["result_id"])
        self.assertEqual((self.root / "var/health-call-count").read_text(), "1")
        self.assertEqual(len(list(self.outbox.glob("*response.json"))), 1)

    def test_wrong_reviewed_hash_rejects_before_claim_and_execution(self):
        item, _ = self.task()
        status, _ = self.run_task(item, "0" * 64)
        self.assertEqual(status, 1)
        self.assertEqual(self.database.get_message(item["id"])["status"], "received")
        self.assertFalse((self.root / "var/health-call-count").exists())

    def test_action_and_mutating_scope_reject_before_claim(self):
        for action, paths in [("deploy", ["var/outbox"]), ("health", ["scripts/check-system.py"])]:
            with self.subTest(action=action, paths=paths):
                item, digest = self.task(action=action, paths=paths)
                status, response = self.run_task(item, digest)
                self.assertEqual(status, 1)
                self.assertEqual(response["error"], "unsupported_task_action")
                self.assertEqual(self.database.get_message(item["id"])["status"], "received")

    def test_dirty_checkout_and_wrong_head_reject_without_health(self):
        item, digest = self.task()
        (self.root / "unexpected.txt").write_text("local change")
        self.assertEqual(self.run_task(item, digest)[0], 1)
        self.git("add", "unexpected.txt")
        self.git("commit", "-qm", "different head")
        self.assertEqual(self.run_task(item, digest)[0], 1)
        self.assertFalse((self.root / "var/health-call-count").exists())

    def test_private_regular_selected_paths_required(self):
        item, digest = self.task()
        self.database.database.chmod(0o644)
        self.assertEqual(self.run_task(item, digest)[1]["error"], "unsafe_local_path")
        self.database.database.chmod(0o600)
        moved = self.root / "var/old-inbox"
        self.inbox.rename(moved)
        self.inbox.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.run_task(item, digest)[1]["error"], "unsafe_local_path")
        self.inbox.unlink()
        os.mkfifo(self.inbox, 0o600)
        self.assertEqual(self.run_task(item, digest)[1]["error"], "unsafe_local_path")

    def test_existing_processing_task_does_not_resume_or_reclaim(self):
        item, digest = self.task()
        worker.accept_task(self.database, self.root, item["id"], digest)
        status, response = self.run_task(item, digest)
        self.assertEqual(status, 1)
        self.assertEqual(response["error"], "task_not_available")
        self.assertFalse((self.root / "var/health-call-count").exists())

    def test_failed_health_has_correlated_blocked_result_and_failed_status(self):
        self.write_checker(healthy=False)
        self.commit_checker()
        item, digest = self.task()
        status, response = self.run_task(item, digest)
        self.assertEqual(status, 1)
        self.assertEqual(response["verification_verdict"], "BLOCKED")
        self.assertEqual(self.database.get_message(item["id"])["status"], "failed")
        self.assertEqual(self.result_payload(response)["correlation_id"], item["correlation_id"])

    def test_timeout_publishes_only_generic_blocked_evidence(self):
        self.write_checker(suffix="import time; time.sleep(2)")
        self.commit_checker()
        item, digest = self.task()
        with patch.object(worker, "TIMEOUT_SECONDS", 0.05):
            status, response = self.run_task(item, digest)
        self.assertEqual(status, 1)
        result = self.result_payload(response)["metadata"]["result"]
        self.assertEqual(result["commands"][0]["exit_code"], 124)
        self.assertIn("health_check_timeout", result["risks"])

    def test_malformed_health_or_inconsistent_exit_is_blocked(self):
        self.write_checker(stdout_record={"schema_version": True, "verdict": "PASS", "checks": []})
        self.commit_checker()
        item, digest = self.task()
        status, response = self.run_task(item, digest)
        self.assertEqual(status, 1)
        self.assertEqual(response["verification_verdict"], "BLOCKED")
        self.assertIn("health_check_evidence_unavailable", self.result_payload(response)["metadata"]["result"]["risks"])

    def test_tracked_change_during_health_is_detected_and_blocked(self):
        self.write_checker(suffix="(root/'.gitignore').write_text('var/\\nresearch/engine/.venv/\\n# changed\\n')")
        self.commit_checker()
        item, digest = self.task()
        status, response = self.run_task(item, digest)
        self.assertEqual(status, 1)
        result = self.result_payload(response)["metadata"]["result"]
        self.assertFalse(result["git_state"]["checkout_unchanged"])
        self.assertIn("checkout_changed_during_health_check", result["risks"])

    def test_tampered_duplicate_artifact_rejects_without_rerun(self):
        item, digest = self.task()
        _, first = self.run_task(item, digest)
        Path(first["result_path"]).write_text("{}")
        status, response = self.run_task(item, digest)
        self.assertEqual(status, 1)
        self.assertEqual(response["error"], "result_readback_failed")
        self.assertEqual((self.root / "var/health-call-count").read_text(), "1")

    def test_argument_error_never_echoes_supplied_sensitive_text(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            status = worker.main(["--unexpected", "fixture-sensitive-argument"])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())["error"], "invalid_arguments")
        self.assertNotIn("fixture-sensitive-argument", output.getvalue())

    def test_database_failure_preserves_known_checks_and_normalizes_missing_freshness(self):
        record = {"schema_version": 1, "verdict": "FAIL",
                  "observed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                  "checks": [{"name": name, "ok": name != "database"}
                             for name in sorted(worker.CHECK_NAMES - {"data_freshness"})]}
        healthy, safe, observed = worker.health_evidence(canonical_bytes(record), 1)
        self.assertFalse(healthy)
        self.assertEqual({item["name"] for item in safe}, worker.CHECK_NAMES)
        self.assertFalse(next(item["ok"] for item in safe if item["name"] == "data_freshness"))
        self.assertTrue(next(item["ok"] for item in safe if item["name"] == "architecture"))
        self.assertTrue(observed.endswith("+00:00"))

    def test_health_timestamp_and_success_exit_must_be_consistent(self):
        record = {"schema_version": 1, "verdict": "PASS",
                  "checks": [{"name": name, "ok": True} for name in sorted(worker.CHECK_NAMES)]}
        for observed in ["2026-10-04T00:00:00", "2000-01-01T00:00:00Z", "fixture-hidden-value"]:
            with self.subTest(observed=observed):
                record["observed_at"] = observed
                with self.assertRaises(worker.WorkerError):
                    worker.health_evidence(canonical_bytes(record), 0)
        record["observed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        with self.assertRaises(worker.WorkerError):
            worker.health_evidence(canonical_bytes(record), 1)

    def test_fixed_health_argv_has_no_shell_and_no_inherited_private_environment(self):
        item, digest = self.task(body="arbitrary shell text")
        original_run = subprocess.run
        calls = []
        def inspect_call(command, **kwargs):
            if str(self.checker) in command:
                calls.append((command, kwargs))
            return original_run(command, **kwargs)
        with patch.dict(os.environ, {"PRIVATE_FIXTURE_SECRET": "fixture-hidden-value"}), patch.object(worker.subprocess, "run", side_effect=inspect_call):
            status, response = self.run_task(item, digest)
        self.assertEqual(status, 0, response)
        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertEqual(command, [str(self.root / "research/engine/.venv/bin/python"), "-B", str(self.checker), "--repo-root", str(self.root), "--json"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], worker.TIMEOUT_SECONDS)
        self.assertNotIn("PRIVATE_FIXTURE_SECRET", kwargs["env"])
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")


if __name__ == "__main__":
    unittest.main()
