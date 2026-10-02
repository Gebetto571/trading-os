"""Acceptance coverage for the read-only canonical Parquet snapshot adapter."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

import polars as pl

from research_engine.errors import DatasetIntegrityError
from research_engine.hashing import sha256_bytes
from research_engine import snapshot as snapshot_module
from research_engine.snapshot import build_canonical_snapshot, materialize_canonical_snapshot


_CANONICAL_SCHEMA = {
    "schema_version": pl.String,
    "venue": pl.String,
    "market_type": pl.String,
    "symbol": pl.String,
    "interval": pl.String,
    "open_time": pl.Datetime("us", "UTC"),
    "open": pl.Decimal(precision=38, scale=18),
    "high": pl.Decimal(precision=38, scale=18),
    "low": pl.Decimal(precision=38, scale=18),
    "close": pl.Decimal(precision=38, scale=18),
    "base_asset_volume": pl.Decimal(precision=38, scale=18),
    "close_time": pl.Datetime("us", "UTC"),
    "quote_asset_volume": pl.Decimal(precision=38, scale=18),
    "trade_count": pl.Int64,
    "taker_buy_base_volume": pl.Decimal(precision=38, scale=18),
    "taker_buy_quote_volume": pl.Decimal(precision=38, scale=18),
    "source": pl.String,
    "source_file": pl.String,
}


def _canonical_frame(open_times: list[int], close_offsets: list[int] | None = None) -> pl.DataFrame:
    offsets = close_offsets or [1] * len(open_times)
    decimals = [Decimal("1.000000000000000000")] * len(open_times)
    values = {
        "schema_version": ["1"] * len(open_times),
        "venue": ["binance"] * len(open_times),
        "market_type": ["spot"] * len(open_times),
        "symbol": ["BTCUSDT"] * len(open_times),
        "interval": ["1m"] * len(open_times),
        "open_time": pl.Series(open_times, dtype=pl.Datetime("us", "UTC")),
        "open": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "high": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "low": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "close": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "base_asset_volume": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "close_time": pl.Series(
            [value + offset for value, offset in zip(open_times, offsets)],
            dtype=pl.Datetime("us", "UTC"),
        ),
        "quote_asset_volume": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "trade_count": pl.Series([1] * len(open_times), dtype=pl.Int64),
        "taker_buy_base_volume": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "taker_buy_quote_volume": pl.Series(decimals, dtype=pl.Decimal(precision=38, scale=18)),
        "source": ["fixture"] * len(open_times),
        "source_file": ["fixture.json"] * len(open_times),
    }
    return pl.DataFrame(values, schema=_CANONICAL_SCHEMA)


def _write_partition(root: Path, year: int, month: int, frame: pl.DataFrame) -> Path:
    target = root / f"year={year:04}" / f"month={month:02}" / "candles.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(target, compression="uncompressed", statistics=False)
    return target


class CanonicalSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_deterministic_manifest_preserves_exact_schema_and_input_bytes(self) -> None:
        later = _write_partition(self.root, 2024, 2, _canonical_frame([3, 4]))
        earlier = _write_partition(self.root, 2024, 1, _canonical_frame([1, 2]))
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (later, earlier)}

        first = build_canonical_snapshot(self.root)
        second = build_canonical_snapshot(self.root)

        self.assertEqual(first.manifest, second.manifest)
        self.assertEqual(first.snapshot_id, second.snapshot_id)
        self.assertEqual(
            [entry["path"] for entry in first.manifest["partitions"]],
            ["year=2024/month=01/candles.parquet", "year=2024/month=02/candles.parquet"],
        )
        self.assertEqual(first.manifest["row_count"], 4)
        self.assertEqual(
            first.manifest["series"],
            {"venue": "binance", "market_type": "spot", "symbol": "BTCUSDT", "interval": "1m"},
        )
        self.assertEqual(first.manifest["first_open_time_us"], 1)
        self.assertEqual(first.manifest["last_open_time_us"], 4)
        self.assertEqual(first.manifest["schema"]["open_time"], "Datetime(time_unit='us', time_zone='UTC')")
        self.assertEqual(first.manifest["schema"]["open"], "Decimal(precision=38, scale=18)")
        self.assertEqual(first.manifest["schema"]["trade_count"], "Int64")
        self._assert_canonical_primitives(first.manifest)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})

    def test_manifest_is_defensive_and_content_addressed(self) -> None:
        _write_partition(self.root, 2024, 1, _canonical_frame([1, 2]))

        snapshot = build_canonical_snapshot(self.root)
        exposed_manifest = snapshot.manifest
        exposed_manifest["row_count"] = 999
        exposed_manifest["partitions"][0]["sha256"] = "0" * 64

        self.assertEqual(snapshot.snapshot_id, sha256_bytes(snapshot.canonical_bytes()))
        self.assertEqual(snapshot.manifest["row_count"], 2)
        self.assertNotEqual(snapshot.manifest["partitions"][0]["sha256"], "0" * 64)

    def test_public_materializer_reuses_snapshot_identity_and_defends_frame(self) -> None:
        _write_partition(self.root, 2024, 2, _canonical_frame([3, 4]))
        _write_partition(self.root, 2024, 1, _canonical_frame([1, 2]))

        materialized = materialize_canonical_snapshot(self.root)

        self.assertEqual(materialized.snapshot.snapshot_id, build_canonical_snapshot(self.root).snapshot_id)
        self.assertEqual(materialized.frame.get_column("open_time").cast(pl.Int64).to_list(), [1, 2, 3, 4])
        exposed = materialized.frame
        exposed = exposed.with_columns(pl.lit(999).alias("trade_count"))
        self.assertEqual(materialized.frame.get_column("trade_count").to_list(), [1, 1, 1, 1])

    def test_public_materializer_rejects_path_replacement_after_descriptor_open(self) -> None:
        target = _write_partition(self.root, 2024, 1, _canonical_frame([1]))
        replacement_root = Path(self.temporary.name) / "replacement"
        replacement = _write_partition(replacement_root, 2024, 1, _canonical_frame([99]))
        original_scan = snapshot_module.pl.scan_parquet
        calls = 0

        def replace_only_during_materialization(path: str) -> pl.LazyFrame:
            nonlocal calls
            calls += 1
            if calls == 2:
                os.replace(replacement, target)
            return original_scan(path)

        with mock.patch.object(
            snapshot_module.pl,
            "scan_parquet",
            side_effect=replace_only_during_materialization,
        ):
            with self.assertRaises(DatasetIntegrityError):
                materialize_canonical_snapshot(self.root)

    def test_schema_nulls_versions_and_close_time_fail_closed(self) -> None:
        invalid_schema = _canonical_frame([1]).with_columns(pl.col("trade_count").cast(pl.Float64))
        _write_partition(self.root, 2024, 1, invalid_schema)
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()
        with_null = _canonical_frame([1]).with_columns(pl.lit(None, dtype=pl.String).alias("source"))
        _write_partition(self.root, 2024, 1, with_null)
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()
        bad_version = _canonical_frame([1]).with_columns(pl.lit("2").alias("schema_version"))
        _write_partition(self.root, 2024, 1, bad_version)
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()
        _write_partition(self.root, 2024, 1, _canonical_frame([1], [0]))
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

    def test_duplicate_unordered_and_overlapping_timestamps_fail_closed(self) -> None:
        _write_partition(self.root, 2024, 1, _canonical_frame([1, 1]))
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self._reset_root()
        _write_partition(self.root, 2024, 1, _canonical_frame([2, 1]))
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self._reset_root()
        _write_partition(self.root, 2024, 1, _canonical_frame([1, 2], [100, 1]))
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self._reset_root()
        _write_partition(self.root, 2024, 1, _canonical_frame([1], [100]))
        _write_partition(self.root, 2024, 2, _canonical_frame([2], [1]))
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

    def test_series_identity_drift_fails_closed(self) -> None:
        _write_partition(self.root, 2024, 1, _canonical_frame([1, 2]))
        changed_series = _canonical_frame([3, 4]).with_columns(pl.lit("5m").alias("interval"))
        _write_partition(self.root, 2024, 2, changed_series)
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

    def test_path_tree_symlink_and_mutation_fail_closed(self) -> None:
        _write_partition(self.root, 2024, 1, _canonical_frame([1]))
        (self.root / "unexpected.txt").write_text("not a partition", encoding="utf-8")
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()
        outside = Path(self.temporary.name) / "outside"
        _write_partition(outside, 2024, 1, _canonical_frame([1]))
        try:
            (self.root / "year=2024").symlink_to(outside / "year=2024", target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink fixture unavailable: {error}")
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)

        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()
        with mock.patch(
            "research_engine.snapshot._hash_bound_descriptor",
            side_effect=["a" * 64, "f" * 64],
        ):
            _write_partition(self.root, 2024, 1, _canonical_frame([1]))
            with self.assertRaises(DatasetIntegrityError):
                build_canonical_snapshot(self.root)

    def test_post_open_path_replacements_fail_closed(self) -> None:
        _write_partition(self.root, 2024, 1, _canonical_frame([1]))
        outside = Path(self.temporary.name) / "outside"
        _write_partition(outside, 2024, 1, _canonical_frame([99]))
        original_scan = snapshot_module.pl.scan_parquet

        def replace_year_then_scan(path: str) -> pl.LazyFrame:
            year_path = self.root / "year=2024"
            moved_year_path = self.root / "year=2024-original"
            year_path.rename(moved_year_path)
            try:
                year_path.symlink_to(outside / "year=2024", target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink fixture unavailable: {error}")
            return original_scan(path)

        with mock.patch.object(snapshot_module.pl, "scan_parquet", side_effect=replace_year_then_scan):
            with self.assertRaises(DatasetIntegrityError):
                build_canonical_snapshot(self.root)

        self._reset_root()
        target = _write_partition(self.root, 2024, 1, _canonical_frame([1]))
        replacement_root = Path(self.temporary.name) / "replacement"
        replacement = _write_partition(replacement_root, 2024, 1, _canonical_frame([99]))

        def replace_file_then_scan(path: str) -> pl.LazyFrame:
            os.replace(replacement, target)
            return original_scan(path)

        with mock.patch.object(snapshot_module.pl, "scan_parquet", side_effect=replace_file_then_scan):
            with self.assertRaises(DatasetIntegrityError):
                build_canonical_snapshot(self.root)

    def test_empty_and_noncanonical_roots_fail_closed(self) -> None:
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root)
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(Path("relative-snapshot"))
        _write_partition(self.root, 2024, 1, _canonical_frame([1]))
        with self.assertRaises(DatasetIntegrityError):
            build_canonical_snapshot(self.root / ".." / self.root.name)

    def _assert_canonical_primitives(self, value: object) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                self._assert_canonical_primitives(nested)
            return
        if isinstance(value, list):
            for nested in value:
                self._assert_canonical_primitives(nested)
            return
        self.assertIn(type(value), {int, str})

    def _reset_root(self) -> None:
        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()
