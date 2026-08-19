"""Behavioral and fail-closed acceptance tests for the A0 vertical slice."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

import polars as pl

from research_engine.config import load_config
from research_engine.errors import (
    ConfigError,
    DatasetIntegrityError,
    RegistryBusy,
    RuntimeBoundaryError,
)
from research_engine.hashing import sha256_file
from research_engine.registry import ExperimentRegistry
from research_engine.runner import run_experiment


FIXTURE = ENGINE_ROOT / "fixtures" / "candles_v1.parquet"
MIGRATION = ENGINE_ROOT / "migrations" / "001_experiment_registry.sql"


def write_config(
    directory: Path,
    *,
    dataset_path: Path,
    dataset_sha256: str,
    runtime_dir: str = "runtime-data",
    trial_id: str = "baseline-v1",
    strategy_family_id: str = "deterministic-event-study-v1",
) -> Path:
    config_path = directory / "experiment.toml"
    config_path.write_text(
        "\n".join(
            [
                f'dataset_path = "{dataset_path}"',
                f'dataset_sha256 = "{dataset_sha256}"',
                f'runtime_dir = "{runtime_dir}"',
                f'trial_id = "{trial_id}"',
                f'strategy_family_id = "{strategy_family_id}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


class EngineAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime_parent = ENGINE_ROOT / "runtime"
        self.runtime_parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=self.runtime_parent)
        self.work = Path(self.temporary.name)
        self.fixture_sha256 = sha256_file(FIXTURE)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_lazy_scan_is_used_and_canonical_fixture_is_unchanged(self) -> None:
        before = sha256_file(FIXTURE)
        config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
        )

        with mock.patch("research_engine.runner.pl.scan_parquet", wraps=pl.scan_parquet) as scan:
            outcome = run_experiment(config)

        scan.assert_called_once_with(str(FIXTURE.resolve()))
        self.assertEqual(before, sha256_file(FIXTURE))
        self.assertEqual(
            outcome.canonical_summary["event_study"],
            {
                "down_count": 3,
                "flat_count": 2,
                "net_direction": 0,
                "row_count": 8,
                "up_count": 3,
            },
        )
        self.assertGreater(outcome.telemetry["elapsed_ns"], 0)
        self.assertGreaterEqual(outcome.telemetry["rows_per_second_integer"], 0)

    def test_same_input_and_config_reuses_the_same_canonical_result(self) -> None:
        config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
        )
        first = run_experiment(config)
        second = run_experiment(config)

        self.assertFalse(first.reused_registry_result)
        self.assertTrue(second.reused_registry_result)
        self.assertEqual(first.canonical_summary, second.canonical_summary)
        self.assertEqual(first.result_artifact_id, second.result_artifact_id)

    def test_missing_dataset_fails_before_registry_creation(self) -> None:
        runtime_dir = self.work / "runtime-data"
        config = write_config(
            self.work,
            dataset_path=self.work / "missing.parquet",
            dataset_sha256=self.fixture_sha256,
        )

        with self.assertRaises(DatasetIntegrityError):
            run_experiment(config)
        self.assertFalse((runtime_dir / "experiments.sqlite3").exists())

    def test_hash_changed_dataset_fails_closed_before_registry_creation(self) -> None:
        runtime_dir = self.work / "runtime-data"
        config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256="0" * 64,
        )

        with self.assertRaises(DatasetIntegrityError):
            run_experiment(config)
        self.assertFalse((runtime_dir / "experiments.sqlite3").exists())

    def test_dataset_changed_during_scan_fails_closed_before_registry_creation(self) -> None:
        runtime_dir = self.work / "runtime-data"
        config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
        )
        with mock.patch(
            "research_engine.runner.sha256_file",
            side_effect=[self.fixture_sha256, "f" * 64],
        ):
            with self.assertRaises(DatasetIntegrityError):
                run_experiment(config)
        self.assertFalse((runtime_dir / "experiments.sqlite3").exists())

    def test_symlinked_dataset_fails_closed(self) -> None:
        link = self.work / "fixture-link.parquet"
        try:
            link.symlink_to(FIXTURE)
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        config = write_config(
            self.work,
            dataset_path=link,
            dataset_sha256=self.fixture_sha256,
        )

        with self.assertRaises(DatasetIntegrityError):
            run_experiment(config)

    def test_schema_invalid_dataset_fails_closed(self) -> None:
        invalid = self.work / "invalid.parquet"
        pl.DataFrame(
            {"open_time": [1], "close": [2]},
            schema={"open_time": pl.Int64, "close": pl.Int64},
        ).write_parquet(invalid, compression="uncompressed", statistics=False)
        config = write_config(
            self.work,
            dataset_path=invalid,
            dataset_sha256=sha256_file(invalid),
        )

        with self.assertRaises(DatasetIntegrityError):
            run_experiment(config)

    def test_config_rejects_remote_and_out_of_root_runtime_paths(self) -> None:
        remote_config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
        )
        remote_config.write_text(
            remote_config.read_text(encoding="utf-8").replace(
                str(FIXTURE), "https://example.invalid/data.parquet"
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ConfigError):
            load_config(remote_config)

        unsafe_runtime = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
            runtime_dir="/private/tmp/not-allowed",
        )
        with self.assertRaises(ConfigError):
            run_experiment(unsafe_runtime)

    def test_registry_rejects_a_second_active_writer(self) -> None:
        database = self.work / "registry.sqlite3"
        registry = ExperimentRegistry(database, MIGRATION)
        registry.initialize()
        holder = sqlite3.connect(database, isolation_level=None)
        try:
            holder.execute("BEGIN IMMEDIATE")
            with self.assertRaises(RegistryBusy):
                registry.record_or_reuse(
                    experiment_id="e" * 64,
                    trial_id="trial",
                    strategy_family_id="family",
                    dataset_path="/read-only/input.parquet",
                    dataset_identity="d" * 64,
                    dataset_sha256="a" * 64,
                    code_sha256="b" * 64,
                    config_sha256="c" * 64,
                    started_at_ns=1,
                    finished_at_ns=2,
                    result_artifact_id="f" * 64,
                    canonical_summary={"result": "stable"},
                )
        finally:
            holder.execute("ROLLBACK")
            holder.close()

    def test_runtime_and_database_symlinks_fail_closed_without_escape(self) -> None:
        runtime_link = self.work / "runtime-link"
        try:
            runtime_link.symlink_to(self.work / "elsewhere")
        except OSError as error:
            self.skipTest(f"symlink creation unavailable: {error}")
        runtime_link_config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
            runtime_dir="runtime-link",
        )
        with self.assertRaises(ConfigError):
            run_experiment(runtime_link_config)

        guarded_runtime = self.work / "guarded-runtime"
        guarded_runtime.mkdir()
        database_link = guarded_runtime / "experiments.sqlite3"
        escape_target = ENGINE_ROOT.parent / "registry-escape.sqlite3"
        self.assertFalse(escape_target.exists())
        database_link.symlink_to(escape_target)
        database_link_config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
            runtime_dir="guarded-runtime",
        )
        with self.assertRaises(RuntimeBoundaryError):
            run_experiment(database_link_config)
        self.assertFalse(escape_target.exists())

    def test_cli_runs_as_an_independent_process_and_returns_json(self) -> None:
        config = write_config(
            self.work,
            dataset_path=FIXTURE,
            dataset_sha256=self.fixture_sha256,
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(ENGINE_ROOT)
        completed = subprocess.run(
            [sys.executable, "-m", "research_engine", "--config", str(config)],
            check=False,
            capture_output=True,
            cwd=ENGINE_ROOT,
            env=environment,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["canonical_summary"]["event_study"]["row_count"], 8)
        self.assertIn("elapsed_ns", payload["telemetry"])
