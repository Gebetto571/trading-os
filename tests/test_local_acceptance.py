import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from trading_os_bridge import cli
from trading_os_bridge.local_acceptance import AcceptanceError, accept_task, validate_task
from trading_os_bridge.store import Store
from trading_os_bridge.validation import canonical_bytes, sha256_bytes


MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


class LocalAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        (self.repo / "tests").mkdir()
        (self.repo / "tests/allowed.py").write_text("value = 1\n")
        (self.repo / ".gitignore").write_text("var/\n.env\n.env.*\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "fixture")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.database = Store(self.base / "bridge.db", MIGRATIONS)
        self.database.migrate()

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(
            ["git", "-C", str(self.repo), *arguments], check=True, capture_output=True,
            text=True, env=env,
        ).stdout

    def task(self, paths=None, base=None):
        paths = ["tests/allowed.py"] if paths is None else paths
        payload = {
            "schema_version": 1, "id": str(uuid.uuid4()),
            "created_at": "2026-10-04T12:00:00Z", "sender": "chatgpt",
            "recipient": "codex-local", "type": "task", "subject": "Health evidence",
            "body": "Read local health only.", "correlation_id": None, "artifacts": [],
            "metadata": {
                "project_domain": "00", "cloud_conversation_key": "tos-cloud-00",
                "local_lane": "chief-engineer/00", "authority": "chief-engineer",
                "approval_state": "approved_for_local_implementation", "change_mode": "STRICT",
                "local_action": "health",
                "implementation_brief": {
                    "outcome": "Report local health", "approved_logic": ["Read only"],
                    "in_scope": ["Health evidence"], "non_goals": ["PAPER and LIVE remain off"],
                    "acceptance_criteria": ["Correlated evidence"], "required_tests": [],
                    "risks": [], "stop_conditions": ["Identity mismatch"],
                },
                "FROZEN_OWNED_PATHS": paths,
                "SCOPE_BINDING_MANIFEST": {
                    "active_writer_principal": "chief-engineer",
                    "canonical_lane": "chief-engineer/00",
                    "expected_base_commit": self.head if base is None else base,
                    "exact_owned_paths": paths,
                },
            },
        }
        return payload

    def record(self, payload):
        self.database.put_message(payload, "inbound", "received")
        return sha256_bytes(canonical_bytes(payload))

    def accept(self, payload, digest=None):
        return accept_task(
            self.database, self.repo, payload["id"],
            sha256_bytes(canonical_bytes(payload)) if digest is None else digest,
        )

    def assert_rejected_without_claim(self, payload, digest=None):
        before = dict(self.database.get_message(payload["id"]))
        with self.assertRaises(AcceptanceError):
            self.accept(payload, digest)
        self.assertEqual(before, dict(self.database.get_message(payload["id"])))

    def test_exact_acceptance_binds_reviewed_hash_and_duplicate_never_reclaims(self):
        payload = self.task(paths=["var/outbox"])
        digest = self.record(payload)
        snapshot = validate_task(self.database, self.repo, payload["id"], digest)
        self.assertEqual(snapshot["base_commit"], self.head)
        self.assertEqual(self.database.get_message(payload["id"])["status"], "received")
        row = self.accept(payload, digest)
        self.assertEqual(row["status"], "processing")
        self.assertEqual(row["base_commit"], self.head)
        self.assertEqual(row["payload_sha256"], digest)
        self.assertEqual(row["active_writer"], "chief-engineer")
        self.assertEqual(json.loads(row["owned_paths_json"]), ["var/outbox"])
        self.assert_rejected_without_claim(payload, digest)
        self.assertEqual(self.database.get_message(payload["id"])["attempt_count"], 1)

    def test_old_actual_head_rejects_even_when_manifest_and_cli_would_agree(self):
        payload = self.task()
        self.record(payload)
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "--allow-empty", "-qm", "new source")
        self.assert_rejected_without_claim(payload)

    def test_head_change_during_claim_is_not_returned_as_accepted(self):
        payload = self.task()
        self.record(payload)
        claim = self.database.claim_chief_engineer_task_by_id

        def claim_then_move_head(*args, **kwargs):
            row = claim(*args, **kwargs)
            self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                     "commit", "--allow-empty", "-qm", "concurrent source change")
            return row

        with patch.object(self.database, "claim_chief_engineer_task_by_id", side_effect=claim_then_move_head):
            with self.assertRaises(AcceptanceError):
                self.accept(payload)
        self.assertEqual(self.database.get_message(payload["id"])["status"], "failed")

    def test_incorrect_or_raw_json_hash_does_not_authorize_the_task(self):
        payload = self.task()
        self.record(payload)
        for digest in ("0" * 64, "", "invalid", sha256_bytes(json.dumps(payload, indent=2).encode())):
            with self.subTest(digest_kind=len(digest)):
                self.assert_rejected_without_claim(payload, digest)

    def test_stored_payload_tampering_is_rejected_even_with_original_stored_hash(self):
        payload = self.task()
        digest = self.record(payload)
        changed = dict(payload, body="Different instructions")
        with self.database.connect() as connection:
            connection.execute("UPDATE messages SET payload_json=? WHERE id=?",
                               (json.dumps(changed), payload["id"]))
        self.assert_rejected_without_claim(payload, digest)

    def test_tracked_dirty_checkout_is_rejected(self):
        payload = self.task()
        self.record(payload)
        (self.repo / "tests/allowed.py").write_text("value = 2\n")
        self.assert_rejected_without_claim(payload)

    def test_untracked_dirty_checkout_is_rejected_even_outside_frozen_paths(self):
        payload = self.task()
        self.record(payload)
        (self.repo / "unrelated.txt").write_text("existing user work\n")
        self.assert_rejected_without_claim(payload)

    def test_staged_dirty_checkout_is_rejected(self):
        payload = self.task()
        self.record(payload)
        (self.repo / "tests/allowed.py").write_text("value = 2\n")
        self.git("add", "tests/allowed.py")
        self.assert_rejected_without_claim(payload)

    def test_ignored_private_files_do_not_require_reading_or_removing_them(self):
        payload = self.task(paths=["var/outbox"])
        self.record(payload)
        (self.repo / ".env").write_text("PRIVATE_FIXTURE=not-for-output\n")
        self.assertEqual(self.accept(payload)["status"], "processing")

    def test_protected_root_and_noncanonical_paths_are_rejected(self):
        for path in (
            ".", ".git", ".git/config", ".env", ".env.local", "sources", "sources/a.json",
            "SOURCES/a.json", "./tests/allowed.py", "tests//allowed.py", "tests/../other.py",
            "/tmp/outside.py", "tests\\outside.py",
        ):
            with self.subTest(path=path):
                payload = self.task(paths=[path])
                self.record(payload)
                self.assert_rejected_without_claim(payload)

    def test_committed_symlink_escape_is_rejected_with_clean_checkout(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.repo / "linked").symlink_to(outside, target_is_directory=True)
        self.git("add", "linked")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "fixture link")
        self.head = self.git("rev-parse", "HEAD").strip()
        self.assertEqual(self.git("status", "--porcelain"), "")
        payload = self.task(paths=["linked/new.py"])
        self.record(payload)
        self.assert_rejected_without_claim(payload)

    def test_self_declared_approval_without_exact_frozen_scope_is_rejected(self):
        payload = self.task()
        del payload["metadata"]["SCOPE_BINDING_MANIFEST"]
        self.record(payload)
        self.assert_rejected_without_claim(payload)

    def test_manifest_and_owned_path_disagreement_is_rejected(self):
        payload = self.task()
        payload["metadata"]["SCOPE_BINDING_MANIFEST"]["exact_owned_paths"] = ["tests/other.py"]
        self.record(payload)
        self.assert_rejected_without_claim(payload)

    def test_short_base_commit_is_rejected(self):
        payload = self.task(base=self.head[:7])
        self.record(payload)
        self.assert_rejected_without_claim(payload)

    def test_fixed_git_root_does_not_accept_subdirectory_or_inherited_git_redirect(self):
        payload = self.task()
        digest = self.record(payload)
        with self.assertRaises(AcceptanceError):
            validate_task(self.database, self.repo / "tests", payload["id"], digest)
        with patch.dict(os.environ, {"GIT_DIR": str(self.base / "absent.git"),
                                     "GIT_WORK_TREE": str(self.base)}):
            self.assertEqual(self.accept(payload)["status"], "processing")

    def test_second_mutating_task_is_rejected_even_for_different_paths(self):
        first = self.task()
        second = self.task(paths=["tests/second.py"])
        self.record(first)
        self.record(second)
        self.accept(first)
        self.assert_rejected_without_claim(second)

    def test_task_text_is_never_executed(self):
        sentinel = self.base / "must-not-exist"
        payload = self.task()
        payload["body"] = "touch " + str(sentinel)
        payload["metadata"]["implementation_brief"]["required_tests"] = [payload["body"]]
        self.record(payload)
        self.accept(payload)
        self.assertFalse(sentinel.exists())

    def test_cli_requires_its_own_repository_and_returns_only_acceptance_summary(self):
        payload = self.task()
        digest = self.record(payload)
        args = cli.parser().parse_args([
            "accept-task", "--id", payload["id"], "--reviewed-sha256", digest,
            "--repo", str(self.repo),
        ])
        with patch.object(cli, "ROOT", self.repo), patch.object(cli, "store", return_value=self.database):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(args.func(args), 0)
            result = json.loads(stdout.getvalue())
            self.assertTrue(result["accepted"])
            self.assertEqual(result["payload_sha256"], digest)
            self.assertEqual(set(result), {
                "accepted", "id", "payload_sha256", "base_commit", "local_lane",
                "owned_paths", "lease_until",
            })
            args.repo = str(self.base)
            with contextlib.redirect_stdout(io.StringIO()), patch.object(cli, "store") as factory:
                self.assertEqual(args.func(args), 1)
                factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
