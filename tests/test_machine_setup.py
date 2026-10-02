from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = (
    "POSTGRES_USER=fixture\nPOSTGRES_PASSWORD=fixture-password\n"
    "POSTGRES_DB=fixture\nPOSTGRES_PORT=54329\n"
    "DATABASE_URL=postgres://fixture:fixture-password@localhost:54329/fixture\n"
)


class MachineSetupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.repo = self.base / "checkout with spaces"
        self.home = self.base / "home with spaces"
        self.runtime = self.home / "Library/Application Support/TradingOS/market-data"
        self.repo.mkdir()
        self.home.mkdir()
        for name in (
            "scripts/lib/market-data.sh", "scripts/check-system.py",
            "scripts/setup-mac-mini.sh", "scripts/deploy-market-data.sh",
            "scripts/sync-btcusdt.sh",
            "ops/launchd/com.tradingos.market-data.btcusdt-sync.plist",
        ):
            destination = self.repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
        (self.repo / ".gitignore").write_text(".env\ntarget/\ndata/\n")
        (self.repo / ".env.example").write_text(ENVIRONMENT.replace("fixture-password", "change-me"))
        self.envfile = self.repo / ".env"
        self.envfile.write_text(ENVIRONMENT)
        self.envfile.chmod(0o600)
        self.environment = os.environ.copy()
        self.environment.update({
            "HOME": str(self.home), "TRADING_OS_PYTHON": sys.executable,
            "TRADING_OS_RUNTIME_ROOT": str(self.runtime), "PYTHONDONTWRITEBYTECODE": "1",
        })
        self.environment.pop("TRADING_OS_MARKET_DATA_HEALTH_DIR", None)
        for args in (
            ["init", "-q"], ["add", "."],
            ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "Fixture"],
        ):
            subprocess.run(["git", *args], cwd=self.repo, env=self.environment,
                           capture_output=True, check=True)

    def command(self, arguments, *, environment=None):
        return subprocess.run(arguments, cwd=self.repo, env=environment or self.environment,
                              text=True, capture_output=True, timeout=30)

    def script(self, name, *arguments, environment=None):
        return self.command(["/bin/bash", str(self.repo / "scripts" / name), *arguments],
                            environment=environment)

    def helper(self, *arguments):
        return self.command([
            "/bin/bash", "-c",
            'source "$1/scripts/lib/market-data.sh"; tos_init "$1"; shift; tos_python_action "$@"',
            "helper", str(self.repo), *arguments,
        ])

    def json_file(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def state(self):
        return json.loads((self.runtime / "active.json").read_text())

    def release(self, script):
        content = script.encode()
        sha = hashlib.sha256(content).hexdigest()
        relative = "releases/" + sha
        folder = self.runtime / relative
        folder.mkdir(parents=True)
        binary = folder / "market-data-import"
        binary.write_bytes(content)
        binary.chmod(0o500)
        self.json_file(folder / "manifest.json", {
            "schema_version": 1, "verdict": "PASS", "sha256": sha,
            "source_commit": "a" * 40, "source_tree_sha256": "b" * 64,
            "test_report_sha256": "c" * 64,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
        self.json_file(self.runtime / "active.json", {
            "schema_version": 1, "current": relative, "previous": None,
        })
        return binary

    def prepare_candidate(self, native="/usr/bin/true"):
        binary = self.repo / "target/release/market-data-import"
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(native, binary)
        binary.chmod(0o700)
        tree = self.helper("source-hash").stdout.strip()
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        result = self.helper("candidate", tree, commit)
        self.assertEqual(result.returncode, 0, result.stderr)
        candidate = json.loads((self.repo / "target/deploy-market-data/candidate.json").read_text())
        report = self.repo / "target/test-project/latest.json"
        self.json_file(report, {
            "schema_version": 1, "verdict": "PASS", "isolated_database": True,
            "container_cleanup_verified": True,
            "bridge_research_tests_status": "PASS", "rust_tests_status": "PASS",
            "python_version": "3.12.14", "rust_version": "rustc 1.88.0 (fixture)",
            "source_commit": candidate["source_commit"],
            "source_tree_sha256": candidate["source_tree_sha256"],
        })
        return report

    def test_repeat_setup_preserves_environment_and_renders_user_paths(self):
        original = self.envfile.read_bytes()
        for _ in range(2):
            result = self.script("setup-mac-mini.sh", "--config-only")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.envfile.read_bytes(), original)
            self.assertEqual(self.envfile.stat().st_mode & 0o777, 0o600)
        installed = self.home / "Library/LaunchAgents/com.tradingos.market-data.btcusdt-sync.plist"
        plist = plistlib.loads(installed.read_bytes())
        self.assertEqual(plist["WorkingDirectory"], str(self.repo))
        self.assertEqual(plist["ProgramArguments"], ["/bin/bash", str(self.repo / "scripts/sync-btcusdt.sh")])
        self.assertEqual(plist["EnvironmentVariables"]["TRADING_OS_RUNTIME_ROOT"], str(self.runtime))
        self.assertNotIn("fixture-password", installed.read_text())
        self.assertFalse((self.runtime / "active.json").exists())

    def test_new_environment_is_private_and_is_not_overwritten(self):
        self.envfile.unlink()
        result = self.script("setup-mac-mini.sh", "--config-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.envfile.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.envfile.read_bytes(), (self.repo / ".env.example").read_bytes())

    def test_world_readable_environment_is_rejected_without_rewriting(self):
        self.envfile.chmod(0o644)
        before = self.envfile.read_bytes()
        result = self.script("setup-mac-mini.sh", "--config-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.envfile.read_bytes(), before)
        self.assertEqual(self.envfile.stat().st_mode & 0o777, 0o644)
        self.assertNotIn("fixture-password", result.stdout + result.stderr)

    def test_environment_symlink_is_rejected_and_target_preserved(self):
        other = self.base / "private-input"
        self.envfile.rename(other)
        self.envfile.symlink_to(other)
        result = self.script("setup-mac-mini.sh", "--config-only")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(other.read_text(), ENVIRONMENT)

    def test_environment_content_is_literal_not_shell_execution(self):
        marker = self.base / "executed"
        literal = "$(touch " + str(marker) + ")"
        self.envfile.write_text(ENVIRONMENT + "TRADING_OS_ACTOR='" + literal + "'\n")
        result = self.command([
            "/bin/bash", "-c",
            'source scripts/lib/market-data.sh; tos_init "$PWD"; tos_load_env; printf "%s" "$TRADING_OS_ACTOR"',
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, literal)
        self.assertFalse(marker.exists())

    def test_environment_cannot_replace_path(self):
        self.envfile.write_text(ENVIRONMENT + "PATH=/untrusted\n")
        self.assertNotEqual(self.helper("env").returncode, 0)

    def test_remote_database_url_prevents_collector_execution(self):
        self.envfile.write_text(ENVIRONMENT.replace("@localhost:", "@other-host:"))
        self.release("#!/bin/bash\nexit 99\n")
        result = self.script("sync-btcusdt.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(result.returncode, 99)
        record = json.loads((self.runtime / "health/latest.json").read_text())
        self.assertEqual(record["error"], "environment_rejected")

    def test_missing_release_replaces_old_success_with_fresh_failure(self):
        health = self.runtime / "health/latest.json"
        self.json_file(health, {
            "schema_version": 1, "observed_at": "2020-01-01T00:00:00Z",
            "status": "succeeded", "symbol": "BTCUSDT", "database_reachable": True,
        })
        result = self.script("sync-btcusdt.sh")
        self.assertNotEqual(result.returncode, 0)
        record = json.loads(health.read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["error"], "release_unavailable")
        self.assertNotEqual(record["observed_at"], "2020-01-01T00:00:00Z")
        self.assertEqual(health.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("fixture-password", result.stdout + result.stderr)

    def test_missing_python_still_publishes_private_health_failure(self):
        environment = dict(self.environment, TRADING_OS_PYTHON="/no/such/python")
        result = self.script("sync-btcusdt.sh", environment=environment)
        self.assertNotEqual(result.returncode, 0)
        record = json.loads((self.runtime / "health/latest.json").read_text())
        self.assertEqual(record["error"], "environment_rejected")

    def test_binary_stderr_and_stdout_are_not_written_to_logs(self):
        self.release("#!/bin/bash\nprintf 'fixture-password\\n' >&2\nprintf 'fixture-password\\n'\nexit 42\n")
        result = self.script("sync-btcusdt.sh")
        self.assertEqual(result.returncode, 42)
        self.assertNotIn("fixture-password", result.stdout + result.stderr)
        record = json.loads((self.runtime / "health/latest.json").read_text())
        self.assertEqual(record["error"], "collector_failed")
        self.assertNotIn("fixture-password", (self.runtime / "health/history.jsonl").read_text())

    def test_success_without_new_health_is_rejected(self):
        self.release("#!/bin/bash\nexit 0\n")
        self.json_file(self.runtime / "health/latest.json", {
            "schema_version": 1, "observed_at": "2020-01-01T00:00:00Z",
            "status": "succeeded", "symbol": "BTCUSDT",
        })
        result = self.script("sync-btcusdt.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads((self.runtime / "health/latest.json").read_text())["error"],
                         "health_record_unavailable")

    def test_changed_binary_is_not_executed(self):
        binary = self.release("#!/bin/bash\nexit 0\n")
        binary.chmod(0o700)
        binary.write_text("#!/bin/bash\nexit 99\n")
        result = self.script("sync-btcusdt.sh")
        self.assertNotEqual(result.returncode, 99)
        self.assertEqual(json.loads((self.runtime / "health/latest.json").read_text())["error"],
                         "release_unavailable")

    def test_activation_and_rollback_preserve_both_verified_versions(self):
        first_report = self.prepare_candidate()
        result = self.script("deploy-market-data.sh", "activate", "--report", str(first_report))
        self.assertEqual(result.returncode, 0, result.stderr)
        first = self.state()["current"]
        second_report = self.prepare_candidate("/usr/bin/false")
        result = self.script("deploy-market-data.sh", "activate", "--report", str(second_report))
        self.assertEqual(result.returncode, 0, result.stderr)
        second = self.state()["current"]
        self.assertNotEqual(first, second)
        self.assertEqual(self.state()["previous"], first)
        # Idempotent activation must retain the useful previous version.
        result = self.script("deploy-market-data.sh", "activate", "--report", str(second_report))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["previous"], first)
        result = self.script("deploy-market-data.sh", "rollback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["current"], first)
        self.assertEqual(self.state()["previous"], second)
        self.assertEqual(self.state()["current_acceptance"]["release"], first)
        self.assertEqual(self.state()["previous_acceptance"]["release"], second)

    def test_failed_report_never_changes_the_active_pair(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        old_state = (self.runtime / "active.json").read_bytes()
        report = self.prepare_candidate("/usr/bin/false")
        contents = json.loads(report.read_text())
        contents["container_cleanup_verified"] = False
        self.json_file(report, contents)
        result = self.script("deploy-market-data.sh", "activate", "--report", str(report))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.runtime / "active.json").read_bytes(), old_state)

    def test_same_binary_new_commit_refreshes_acceptance_not_immutable_manifest(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        first_state = self.state()
        report = self.prepare_candidate("/usr/bin/false")
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        before = self.state()
        manifest = self.runtime / before["current"] / "manifest.json"
        immutable_before = manifest.read_bytes()

        (self.repo / "README.md").write_text("Documentation-only revision.\n")
        for args in (
            ["add", "README.md"],
            ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "commit", "-qm", "Documentation only"],
        ):
            subprocess.run(["git", *args], cwd=self.repo, env=self.environment,
                           capture_output=True, check=True)
        report = self.prepare_candidate("/usr/bin/false")
        accepted_report = json.loads(report.read_text())
        result = self.script("deploy-market-data.sh", "activate", "--report", str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        after = self.state()
        self.assertEqual(after["current"], before["current"])
        self.assertEqual(after["previous"], before["previous"])
        self.assertEqual(after["previous_acceptance"], before["previous_acceptance"])
        self.assertEqual(manifest.read_bytes(), immutable_before)
        receipt = after["current_acceptance"]
        self.assertEqual(receipt["source_commit"], accepted_report["source_commit"])
        self.assertEqual(receipt["source_tree_sha256"], accepted_report["source_tree_sha256"])
        self.assertEqual(receipt["test_report_sha256"], hashlib.sha256(report.read_bytes()).hexdigest())
        self.assertEqual(receipt["origin"], "activation")
        self.assertNotEqual(receipt["source_commit"], before["current_acceptance"]["source_commit"])
        self.assertNotEqual(receipt["accepted_at"], before["current_acceptance"]["accepted_at"])

        result = self.script("deploy-market-data.sh", "rollback")
        self.assertEqual(result.returncode, 0, result.stderr)
        rolled_back = self.state()
        self.assertEqual(rolled_back["current"], first_state["current"])
        self.assertEqual(rolled_back["current_acceptance"], first_state["current_acceptance"])
        self.assertEqual(rolled_back["previous_acceptance"], receipt)
        self.assertEqual(self.script("deploy-market-data.sh", "rollback").returncode, 0)
        self.assertEqual(self.state()["current_acceptance"], receipt)

    def test_first_release_has_no_automatic_rollback_and_state_is_preserved(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        self.assertIsNone(self.state()["previous"])
        self.assertIsNone(self.state()["previous_acceptance"])
        before = (self.runtime / "active.json").read_bytes()
        result = self.script("deploy-market-data.sh", "rollback")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.runtime / "active.json").read_bytes(), before)

    def test_legacy_schema_one_uses_explicit_original_manifest_acceptance(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        legacy = self.state()
        legacy.pop("current_acceptance")
        legacy.pop("previous_acceptance")
        self.json_file(self.runtime / "active.json", legacy)
        original = json.loads((self.runtime / legacy["current"] / "manifest.json").read_text())
        report = self.prepare_candidate("/usr/bin/false")
        result = self.script("deploy-market-data.sh", "activate", "--report", str(report))
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt = self.state()["previous_acceptance"]
        self.assertEqual(receipt["origin"], "legacy_manifest")
        self.assertEqual(receipt["source_commit"], original["source_commit"])
        self.assertEqual(receipt["source_tree_sha256"], original["source_tree_sha256"])
        self.assertEqual(receipt["test_report_sha256"], original["test_report_sha256"])
        self.assertEqual(receipt["accepted_at"], original["created_at"])
        self.assertEqual(self.script("deploy-market-data.sh", "rollback").returncode, 0)
        self.assertEqual(self.state()["current_acceptance"], receipt)

    def test_mismatched_previous_acceptance_blocks_rollback_without_writes(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        report = self.prepare_candidate("/usr/bin/false")
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        state = self.state()
        state["previous_acceptance"]["release"] = state["current"]
        self.json_file(self.runtime / "active.json", state)
        before = (self.runtime / "active.json").read_bytes()
        result = self.script("deploy-market-data.sh", "rollback")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.runtime / "active.json").read_bytes(), before)

    def test_explicit_null_current_acceptance_is_not_treated_as_legacy(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        state = self.state()
        state["current_acceptance"] = None
        self.json_file(self.runtime / "active.json", state)
        before = (self.runtime / "active.json").read_bytes()
        self.assertNotEqual(self.script("deploy-market-data.sh", "status").returncode, 0)
        self.assertNotEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        self.assertEqual((self.runtime / "active.json").read_bytes(), before)

    def test_boolean_schema_and_null_previous_receipts_fail_without_state_writes(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        report = self.prepare_candidate("/usr/bin/false")
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        original = self.state()
        for slot, value in (("current", True), ("previous", True), ("previous", None)):
            with self.subTest(slot=slot, value=value):
                state = json.loads(json.dumps(original))
                if value is None:
                    state[slot + "_acceptance"] = None
                else:
                    state[slot + "_acceptance"]["schema_version"] = value
                self.json_file(self.runtime / "active.json", state)
                before = (self.runtime / "active.json").read_bytes()
                operation = "status" if slot == "current" else "rollback"
                result = self.script("deploy-market-data.sh", operation)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.runtime / "active.json").read_bytes(), before)

    def test_source_change_after_build_prevents_activation(self):
        report = self.prepare_candidate()
        (self.repo / "scripts/sync-btcusdt.sh").write_text("# modified after build\n")
        result = self.script("deploy-market-data.sh", "activate", "--report", str(report))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.runtime / "active.json").exists())

    def test_source_change_before_candidate_metadata_cannot_rebind_binary(self):
        report = self.prepare_candidate()
        candidate_path = self.repo / "target/deploy-market-data/candidate.json"
        original = candidate_path.read_bytes()
        candidate = json.loads(original)
        (self.repo / "scripts/new-source.sh").write_text("# added during candidate admission\n")
        result = self.helper("candidate", candidate["source_tree_sha256"], candidate["source_commit"])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(candidate_path.read_bytes(), original)
        self.assertNotEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)

    def test_fifo_history_cannot_hang_a_failure_or_preserve_old_success(self):
        health = self.runtime / "health/latest.json"
        self.json_file(health, {"status": "succeeded"})
        os.mkfifo(health.parent / "history.jsonl", 0o600)
        result = self.script("sync-btcusdt.sh")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(health.read_text())["error"], "release_unavailable")

    def test_corrupt_current_can_still_roll_back_to_good_previous(self):
        report = self.prepare_candidate()
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        previous = self.state()["current"]
        report = self.prepare_candidate("/usr/bin/false")
        self.assertEqual(self.script("deploy-market-data.sh", "activate", "--report", str(report)).returncode, 0)
        binary = self.runtime / self.state()["current"] / "market-data-import"
        binary.chmod(0o700)
        binary.write_text("corrupt")
        result = self.script("deploy-market-data.sh", "rollback")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["current"], previous)

    def test_source_hash_includes_new_files_but_excludes_private_state(self):
        initial = self.helper("source-hash").stdout
        self.envfile.write_text(ENVIRONMENT.replace("fixture-password", "new-fixture-password"))
        data = self.repo / "data/private.txt"
        data.parent.mkdir()
        data.write_text("private-state")
        self.assertEqual(initial, self.helper("source-hash").stdout)
        (self.repo / "scripts/new-check.sh").write_text("# new source\n")
        self.assertNotEqual(initial, self.helper("source-hash").stdout)


if __name__ == "__main__":
    unittest.main()
