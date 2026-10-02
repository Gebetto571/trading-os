"""Failure-path coverage for operations; no production database or Docker needed."""

import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("system_checks", ROOT / "scripts/check-system.py")
CHECKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKS)


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.now = dt.datetime(2026, 10, 2, 12, tzinfo=dt.timezone.utc)

    def tearDown(self):
        self.temporary.cleanup()

    def environment(self, content):
        path = self.root / ".env"
        path.write_text(content)
        path.chmod(0o600)
        return path

    def healthy(self):
        return dict(schema_version=1, symbol="BTCUSDT", observed_at="2026-10-02T11:59:00Z",
                    status="succeeded", database_reachable=True, gaps_remaining=0,
                    last_open_after="2026-10-02T11:58:00Z")

    def test_environment_is_literal_not_shell_code(self):
        marker = self.root / "executed"
        values = CHECKS.load_environment(self.environment(
            "POSTGRES_PASSWORD='$(touch " + str(marker) + ")'\n"))
        self.assertIn("$(touch", values["POSTGRES_PASSWORD"])
        self.assertFalse(marker.exists())

    def test_environment_rejects_public_permissions(self):
        path = self.environment("POSTGRES_USER=test\n")
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            CHECKS.load_environment(path)

    def test_environment_rejects_symlink(self):
        path = self.environment("POSTGRES_USER=test\n")
        link = self.root / "linked"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            CHECKS.load_environment(link)

    def test_environment_rejects_fifo_without_waiting_for_a_writer(self):
        path = self.root / ".env"
        os.mkfifo(path, 0o600)
        code = ("import runpy,sys; "
                "runpy.run_path(sys.argv[1],run_name='checks')['load_environment'](sys.argv[2])")
        result = subprocess.run([sys.executable, "-c", code,
                                 str(ROOT / "scripts/check-system.py"), str(path)],
                                text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ValueError", result.stderr)

    def test_health_accepts_owned_private_regular_record(self):
        path = self.root / "latest.json"
        path.write_text(json.dumps(self.healthy()))
        path.chmod(0o600)
        record = CHECKS.read_private_json(path)
        self.assertTrue(CHECKS.evaluate_health(record, self.now, 1800)["ok"])

    def test_health_rejects_fifo_without_waiting(self):
        path = self.root / "latest.json"
        os.mkfifo(path, 0o600)
        code = ("import runpy,sys; "
                "runpy.run_path(sys.argv[1],run_name='checks')['read_private_json'](sys.argv[2])")
        result = subprocess.run([sys.executable, "-c", code,
                                 str(ROOT / "scripts/check-system.py"), str(path)],
                                text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ValueError", result.stderr)

    def test_health_rejects_symlink_and_public_permissions(self):
        path = self.root / "latest.json"
        path.write_text(json.dumps(self.healthy()))
        path.chmod(0o600)
        link = self.root / "linked.json"
        link.symlink_to(path)
        with self.assertRaises(OSError):
            CHECKS.read_private_json(link)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            CHECKS.read_private_json(path)

    def test_health_rejects_other_owner_and_oversized_record(self):
        path = self.root / "latest.json"
        path.write_text(json.dumps(self.healthy()))
        path.chmod(0o600)
        actual_uid = os.getuid()
        with patch.object(CHECKS.os, "getuid", return_value=actual_uid + 1):
            with self.assertRaises(ValueError):
                CHECKS.read_private_json(path)
        path.write_bytes(b" " * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            CHECKS.read_private_json(path)

    def test_readiness_rejects_nonprivate_health_with_generic_output(self):
        health = self.root / "health"
        health.mkdir(mode=0o700)
        path = health / "latest.json"
        path.write_text(json.dumps(self.healthy()))
        path.chmod(0o644)
        with patch.object(CHECKS, "run", side_effect=OSError("sensitive internal error")):
            result = CHECKS.readiness(self.root, health_directory=health)
        collector = next(item for item in result["checks"] if item["name"] == "collector")
        self.assertFalse(collector["ok"])
        self.assertNotIn("sensitive", json.dumps(result))

    def test_environment_rejects_duplicate_and_malformed_lines(self):
        for content in ("POSTGRES_USER=a\nPOSTGRES_USER=b\n", "source ./other\n", "A=a;touch file\n"):
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    CHECKS.load_environment(self.environment(content))

    def runtime_environment(self):
        return dict(POSTGRES_USER="test_user", POSTGRES_DB="test_db",
                    POSTGRES_PASSWORD="private-pass", POSTGRES_PORT="54329",
                    DATABASE_URL="postgres://test_user:private-pass@localhost:54329/test_db")

    def test_runtime_environment_accepts_consistent_local_uri_and_encoded_credentials(self):
        values = self.runtime_environment()
        CHECKS.validate_runtime_environment(values)
        values["POSTGRES_PASSWORD"] = "private@:/ pass"
        values["DATABASE_URL"] = "postgresql://test_user:private%40%3A%2F%20pass@127.0.0.1:54329/test_db"
        values.pop("POSTGRES_PORT")
        CHECKS.validate_runtime_environment(values)

    def test_runtime_environment_rejects_wrong_host_database_password_and_port(self):
        invalid = (
            "postgres://test_user:private-pass@remote.example:54329/test_db",
            "postgres://test_user:private-pass@localhost:54329/other_db",
            "postgres://test_user:wrong@localhost:54329/test_db",
            "postgres://other:private-pass@localhost:54329/test_db",
            "postgres://test_user:private-pass@localhost:5432/test_db",
        )
        for uri in invalid:
            with self.subTest(uri=uri):
                values = self.runtime_environment()
                values["DATABASE_URL"] = uri
                with self.assertRaises(ValueError) as error:
                    CHECKS.validate_runtime_environment(values)
                self.assertNotIn(uri, str(error.exception))

    def test_runtime_environment_rejects_placeholder_malformed_uri_and_overrides(self):
        values = self.runtime_environment()
        values.update(POSTGRES_PASSWORD="change-me",
                      DATABASE_URL="postgres://test_user:change-me@localhost:54329/test_db")
        with self.assertRaises(ValueError):
            CHECKS.validate_runtime_environment(values)
        for uri in ("not-a-database-uri", "mysql://test_user:private-pass@localhost:54329/test_db",
                    "postgres://test_user:private-pass@localhost:broken/test_db",
                    "postgres://test_user:private-pass@localhost:54329/test_db?host=remote.example",
                    "postgres://test_user:private-pass@localhost:54329/test_db#override",
                    "postgres://test_user:private%XX@localhost:54329/test_db"):
            with self.subTest(uri=uri):
                values = self.runtime_environment()
                values["DATABASE_URL"] = uri
                with self.assertRaises(ValueError):
                    CHECKS.validate_runtime_environment(values)

    def test_runtime_environment_rejects_invalid_numeric_port_missing_values_and_extra_keys(self):
        for port in ("0", "65536", "no-port", ""):
            values = self.runtime_environment()
            values["POSTGRES_PORT"] = port
            with self.subTest(port=port), self.assertRaises(ValueError):
                CHECKS.validate_runtime_environment(values)
        values = self.runtime_environment()
        values.pop("POSTGRES_PASSWORD")
        with self.assertRaises(ValueError):
            CHECKS.validate_runtime_environment(values)
        values = self.runtime_environment()
        values["PATH"] = "/untrusted"
        with self.assertRaises(ValueError):
            CHECKS.validate_runtime_environment(values)

    def test_readiness_cannot_accept_configuration_for_a_different_database(self):
        values = self.runtime_environment()
        values["DATABASE_URL"] = "postgres://test_user:private-pass@localhost:54329/different"
        self.environment("\n".join(key + "=" + value for key, value in values.items()))
        with patch.object(CHECKS, "run", side_effect=OSError("internal credentials")):
            result = CHECKS.readiness(self.root, health_directory=self.root / "health")
        environment = next(item for item in result["checks"] if item["name"] == "environment")
        self.assertFalse(environment["ok"])
        self.assertEqual(result["verdict"], "FAIL")
        self.assertNotIn("private-pass", json.dumps(result))

    def test_latest_failure_cannot_be_green(self):
        record = self.healthy()
        record["status"] = "failed"
        self.assertFalse(CHECKS.evaluate_health(record, self.now, 1800)["ok"])

    def test_recent_noop_with_old_data_cannot_be_green(self):
        record = self.healthy()
        record.update(status="noop", last_open_after="2026-09-24T11:58:00Z")
        self.assertFalse(CHECKS.evaluate_health(record, self.now, 1800)["ok"])

    def test_old_success_cannot_be_green(self):
        record = self.healthy()
        record["observed_at"] = "2026-09-24T11:59:00Z"
        self.assertFalse(CHECKS.evaluate_health(record, self.now, 1800)["ok"])

    def test_future_and_timezone_free_timestamps_are_rejected(self):
        for value in ("2026-10-03T00:00:00Z", "2026-10-02T11:59:00"):
            record = self.healthy()
            record["observed_at"] = value
            with self.assertRaises(ValueError):
                CHECKS.evaluate_health(record, self.now, 1800)

    def test_fresh_success_requires_reachable_database_and_zero_gaps(self):
        record = self.healthy()
        self.assertTrue(CHECKS.evaluate_health(record, self.now, 1800)["ok"])
        record["database_reachable"] = False
        self.assertFalse(CHECKS.evaluate_health(record, self.now, 1800)["ok"])
        record["database_reachable"] = True
        record["gaps_remaining"] = 1
        self.assertFalse(CHECKS.evaluate_health(record, self.now, 1800)["ok"])

    def test_missing_configuration_and_tool_failures_do_not_disclose_errors(self):
        with patch.object(CHECKS, "run", side_effect=subprocess.CalledProcessError(
                1, "tool", stderr="secret-password-must-not-escape")):
            result = CHECKS.readiness(self.root, health_directory=self.root / "health")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertNotIn("secret-password", json.dumps(result))

    def test_readiness_selects_project_rust_pin_outside_the_repository(self):
        expected = self.root.resolve()

        def fake_run(command, **options):
            if command[0] == "rustc":
                return "rustc 1.88.0 (project pin)" if options.get("cwd") == expected else "rustc 1.99.0 (global default)"
            raise OSError("unavailable fixture tool")

        with patch.object(CHECKS, "run", side_effect=fake_run):
            result = CHECKS.readiness(self.root, health_directory=self.root / "health")
        rust = next(item for item in result["checks"] if item["name"] == "rust")
        self.assertTrue(rust["ok"])
        self.assertEqual(rust["detail"], "rustc 1.88.0")

    def deployment_fixture(self):
        data = b"binary fixture"
        sha = hashlib.sha256(data).hexdigest()
        directory = self.root / "releases" / sha
        directory.mkdir(parents=True)
        binary = directory / "market-data-import"
        binary.write_bytes(data)
        binary.chmod(0o700)
        manifest = directory / "manifest.json"
        manifest.write_text(json.dumps(
            dict(schema_version=1, verdict="PASS", sha256=sha, source_commit="a" * 40,
                 source_tree_sha256="b" * 64, test_report_sha256="c" * 64,
                 created_at="2026-10-02T10:00:00Z")))
        state = self.root / "active.json"
        state.write_text(json.dumps(
            dict(schema_version=1, current="releases/" + sha, previous=None)))
        return sha, binary, manifest, state

    def test_active_binary_hash_is_verified(self):
        sha, binary, _, _ = self.deployment_fixture()
        self.assertEqual(CHECKS.inspect_deployment(self.root)["binary_sha256"], sha)
        binary.write_bytes(b"modified")
        with self.assertRaises(ValueError):
            CHECKS.inspect_deployment(self.root)

    def test_same_binary_shows_original_build_and_current_acceptance_separately(self):
        sha, _, _, state = self.deployment_fixture()
        receipt = dict(schema_version=1, release="releases/" + sha,
                       source_commit="d" * 40, source_tree_sha256="e" * 64,
                       test_report_sha256="f" * 64, accepted_at="2026-10-02T11:00:00Z",
                       origin="activation")
        record = json.loads(state.read_text())
        record["current_acceptance"] = receipt
        state.write_text(json.dumps(record))
        result = CHECKS.inspect_deployment(self.root)
        self.assertEqual(result["binary_source_commit"], "a" * 40)
        self.assertEqual(result["accepted_source_commit"], "d" * 40)
        self.assertEqual(result["source_commit"], "d" * 40)
        self.assertEqual(result["accepted_test_report_sha256"], "f" * 64)
        self.assertEqual(result["acceptance_origin"], "activation")

    def test_malformed_acceptance_cannot_be_replaced_by_legacy_fallback(self):
        sha, _, _, state = self.deployment_fixture()
        good = dict(schema_version=1, release="releases/" + sha,
                    source_commit="d" * 40, source_tree_sha256="e" * 64,
                    test_report_sha256="f" * 64, accepted_at="2026-10-02T11:00:00Z",
                    origin="activation")
        invalid = [None, dict(good, schema_version=True), dict(good, release="releases/" + "0" * 64),
                   dict(good, source_commit="invalid"), dict(good, test_report_sha256="missing"),
                   dict(good, accepted_at="2026-10-02T11:00:00"), dict(good, origin="unknown")]
        record = json.loads(state.read_text())
        for receipt in invalid:
            with self.subTest(receipt=receipt):
                record["current_acceptance"] = receipt
                state.write_text(json.dumps(record))
                with self.assertRaises((ValueError, TypeError)):
                    CHECKS.inspect_deployment(self.root)

    def test_legacy_acceptance_requires_original_report_hash_and_time(self):
        _, _, manifest, _ = self.deployment_fixture()
        result = CHECKS.inspect_deployment(self.root)
        self.assertEqual(result["acceptance_origin"], "legacy_manifest")
        self.assertEqual(result["accepted_source_commit"], "a" * 40)
        record = json.loads(manifest.read_text())
        record.pop("test_report_sha256")
        manifest.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            CHECKS.inspect_deployment(self.root)

    def test_active_deployment_rejects_path_escape(self):
        (self.root / "active.json").write_text(json.dumps(
            dict(schema_version=1, current="../../outside", previous=None)))
        with self.assertRaises(ValueError):
            CHECKS.inspect_deployment(self.root)

    def test_malformed_health_object_cannot_pass(self):
        with self.assertRaises(ValueError):
            CHECKS.evaluate_health([], self.now, 1800)
        record = self.healthy()
        record["gaps_remaining"] = False
        self.assertFalse(CHECKS.evaluate_health(record, self.now, 1800)["ok"])


class ShellOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "repo"
        (self.root / "scripts/lib").mkdir(parents=True)
        self.bin = self.base / "mock-bin"
        self.bin.mkdir()
        self.log = self.base / "commands.jsonl"
        for name in ("test-project.sh", "backup-database.sh"):
            shutil.copy2(ROOT / "scripts" / name, self.root / "scripts" / name)
        helper = self.root / "scripts/lib/market-data.sh"
        helper.write_text("""tos_init() { TOS_REPOSITORY_ROOT="$1"; TOS_ENV_FILE="$1/.env"; }
tos_python() { printf '%s\\n' "$MOCK_PYTHON"; }
tos_source_tree_sha256() { printf '%s\\n' 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; }
tos_load_env() { POSTGRES_USER=test_user; POSTGRES_DB=test_db; }
""")
        self.python = self.bin / "python"
        self.python.write_text("#!" + sys.executable + "\n" + """import os, subprocess, sys
if len(sys.argv)>2 and sys.argv[1]=='-c':
    if 'sys.version_info' in sys.argv[2]: print('3.12.14'); sys.exit(0)
    if 'assert polars' in sys.argv[2]: sys.exit(0)
if len(sys.argv)>2 and sys.argv[1:3]==['-m','unittest']:
    with open(os.environ['MOCK_LOG'],'a') as stream: stream.write('python-test\\n')
    sys.exit(0)
os.execv(os.environ['REAL_PYTHON'],[os.environ['REAL_PYTHON'],*sys.argv[1:]])
""")
        self.python.chmod(0o700)
        self.mock("rustc", "print('rustc 1.88.0 (fixture)')")
        self.mock("git", "print('abc123')")
        self.mock("cargo", "import os; sys.exit(7 if os.environ.get('MOCK_CARGO_FAIL') else 0)")
        self.mock("docker", """import json, os
args=sys.argv[1:]
with open(os.environ['MOCK_LOG'],'a') as stream: stream.write(json.dumps(args)+'\\n')
state=os.environ['MOCK_OWNER']
if args[0]=='run':
    owner=next(v.split('=',1)[1] for v in args if v.startswith('trading-os.test-owner='))
    open(state,'w').write(owner)
elif args[0]=='inspect':
    print('54321' if 'HostPort' in args[2] else open(state).read())
elif args[0]=='rm':
    os.unlink(state)
elif 'pg_dump' in args:
    if os.environ.get('MOCK_DUMP_FAIL'): sys.exit(9)
    sys.stdout.buffer.write(b'PGDMP fixture archive')
elif 'pg_restore' in args:
    if os.environ.get('MOCK_RESTORE_FAIL'): sys.exit(9)
    sys.stdin.buffer.read(); print('fixture archive contents')
""")
        self.environment = dict(os.environ)
        self.environment.pop("DATABASE_URL", None)
        self.environment.update(PATH=str(self.bin) + os.pathsep + os.environ.get("PATH", ""),
                                MOCK_PYTHON=str(self.python), REAL_PYTHON=sys.executable,
                                MOCK_LOG=str(self.log), MOCK_OWNER=str(self.base / "owner"))

    def tearDown(self):
        self.temporary.cleanup()

    def mock(self, name, body):
        path = self.bin / name
        path.write_text("#!" + sys.executable + "\nimport sys\n" + body + "\n")
        path.chmod(0o700)

    def invoke(self, name, *arguments, cwd=None):
        return subprocess.run(["bash", str(self.root / "scripts" / name), *map(str, arguments)],
                              env=self.environment, cwd=cwd, text=True, capture_output=True, timeout=15)

    def test_full_runner_refuses_any_inherited_database_url(self):
        self.environment["DATABASE_URL"] = "postgres://production-secret@example/production"
        result = self.invoke("test-project.sh")
        self.assertEqual(result.returncode, 64)
        self.assertFalse(self.log.exists())
        self.assertNotIn("production-secret", result.stdout + result.stderr)

    def test_full_runner_uses_project_pin_when_called_from_another_directory(self):
        self.environment["MOCK_EXPECTED_CWD"] = str(self.root)
        self.mock("rustc", "import os; print('rustc 1.88.0 (project pin)' if os.getcwd() == os.environ['MOCK_EXPECTED_CWD'] else 'rustc 1.99.0 (global default)')")
        report = self.base / "outside-report.json"
        result = self.invoke("test-project.sh", "--report-file", report, cwd=self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(report.read_text())["rust_version"], "rustc 1.88.0 (project pin)")

    def test_full_runner_uses_loopback_ephemeral_volume_and_owned_cleanup(self):
        report = self.base / "report.json"
        result = self.invoke("test-project.sh", "--report-file", report)
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(report.read_text())
        self.assertEqual(record["verdict"], "PASS")
        self.assertTrue(record["isolated_database"])
        self.assertTrue(record["container_cleanup_verified"])
        lines = self.log.read_text().splitlines()
        calls = [json.loads(line) for line in lines if line.startswith("[")]
        start = next(call for call in calls if call[0] == "run")
        self.assertIn("127.0.0.1::5432", start)
        self.assertIn("--tmpfs", start)
        self.assertNotIn("-v", start)
        self.assertTrue(any(call[0] == "rm" for call in calls))
        self.assertEqual(lines.count("python-test"), 2)
        self.assertFalse((self.base / "owner").exists())

    def test_full_runner_failure_still_cleans_owned_container(self):
        self.environment["MOCK_CARGO_FAIL"] = "1"
        report = self.base / "failed.json"
        result = self.invoke("test-project.sh", "--report-file", report)
        self.assertNotEqual(result.returncode, 0)
        record = json.loads(report.read_text())
        self.assertEqual(record["verdict"], "FAIL")
        self.assertTrue(record["container_cleanup_verified"])
        self.assertFalse((self.base / "owner").exists())

    def test_backup_is_private_hashed_and_does_not_claim_restoration(self):
        destination = self.base / "backups"
        result = self.invoke("backup-database.sh", "--destination", destination)
        self.assertEqual(result.returncode, 0, result.stderr)
        directory = next(destination.iterdir())
        manifest = json.loads((directory / "manifest.json").read_text())
        archive = directory / manifest["archive"]
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), manifest["sha256"])
        self.assertTrue(manifest["archive_list_verified"])
        self.assertFalse(manifest["restore_verified"])
        self.assertFalse(manifest["separate_physical_disk_verified"])
        self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
        for file in directory.iterdir():
            self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_backup_rejects_destination_inside_repository(self):
        result = self.invoke("backup-database.sh", "--destination", self.root / "backups")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_backup_rejects_symlink_directory(self):
        directory = self.base / "backups"
        directory.mkdir()
        link = self.base / "linked"
        link.symlink_to(directory)
        result = self.invoke("backup-database.sh", "--destination", link)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_failed_archive_validation_never_produces_success_manifest(self):
        self.environment["MOCK_RESTORE_FAIL"] = "1"
        destination = self.base / "backups"
        result = self.invoke("backup-database.sh", "--destination", destination)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(list(destination.glob("*/manifest.json")))
        self.assertFalse(list(destination.glob("*/market-data.dump")))
        self.assertFalse(list(destination.glob("*/market-data.dump.part")))


if __name__ == "__main__":
    unittest.main()
