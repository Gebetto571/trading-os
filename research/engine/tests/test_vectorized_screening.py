"""Acceptance tests for deterministic, read-only R1 vectorized screening."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

import polars as pl

from research_engine.errors import DatasetIntegrityError
from research_engine.hashing import canonical_bytes, sha256_bytes
from research_engine.screening import (
    ScreeningConfig,
    _decimal_to_scaled_i64,
    screen_canonical_snapshot,
)


_SCHEMA = {
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


def _frame(open_times: list[int], deltas: list[Decimal]) -> pl.DataFrame:
    open_values = [Decimal("1.000000000000000000")] * len(open_times)
    close_values = [open_value + delta for open_value, delta in zip(open_values, deltas)]
    return pl.DataFrame(
        {
            "schema_version": ["1"] * len(open_times),
            "venue": ["fixture"] * len(open_times),
            "market_type": ["spot"] * len(open_times),
            "symbol": ["TESTUSD"] * len(open_times),
            "interval": ["1m"] * len(open_times),
            "open_time": pl.Series(open_times, dtype=pl.Datetime("us", "UTC")),
            "open": pl.Series(open_values, dtype=pl.Decimal(precision=38, scale=18)),
            "high": pl.Series(close_values, dtype=pl.Decimal(precision=38, scale=18)),
            "low": pl.Series(open_values, dtype=pl.Decimal(precision=38, scale=18)),
            "close": pl.Series(close_values, dtype=pl.Decimal(precision=38, scale=18)),
            "base_asset_volume": pl.Series(open_values, dtype=pl.Decimal(precision=38, scale=18)),
            "close_time": pl.Series(
                [value + 1 for value in open_times], dtype=pl.Datetime("us", "UTC")
            ),
            "quote_asset_volume": pl.Series(open_values, dtype=pl.Decimal(precision=38, scale=18)),
            "trade_count": pl.Series([1] * len(open_times), dtype=pl.Int64),
            "taker_buy_base_volume": pl.Series(
                open_values, dtype=pl.Decimal(precision=38, scale=18)
            ),
            "taker_buy_quote_volume": pl.Series(
                open_values, dtype=pl.Decimal(precision=38, scale=18)
            ),
            "source": ["fixture"] * len(open_times),
            "source_file": ["fixture.json"] * len(open_times),
        },
        schema=_SCHEMA,
    )


def _write_partition(root: Path, year: int, month: int, frame: pl.DataFrame) -> Path:
    target = root / f"year={year:04}" / f"month={month:02}" / "candles.parquet"
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(target, compression="uncompressed", statistics=False)
    return target


class VectorizedScreeningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "snapshot"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _populate(self, root: Path, reverse_creation: bool = False) -> tuple[Path, ...]:
        first = (2024, 1, _frame([1, 2], [Decimal("0.000000000000000002"), Decimal("-0.000000000000000003")]))
        second = (2024, 2, _frame([3, 4], [Decimal("0.000000000000000005"), Decimal("-0.000000000000000008")]))
        entries = [first, second]
        if reverse_creation:
            entries.reverse()
        return tuple(_write_partition(root, *entry) for entry in entries)

    def test_repeatable_output_is_independent_of_partition_creation_order(self) -> None:
        first_paths = self._populate(self.root, reverse_creation=True)
        second_root = Path(self.temporary.name) / "second"
        second_root.mkdir()
        second_paths = self._populate(second_root, reverse_creation=False)
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (*first_paths, *second_paths)
        }
        config = ScreeningConfig("generic_screening_v1", (2, 5))

        first = screen_canonical_snapshot(self.root, config)
        second = screen_canonical_snapshot(second_root, config)

        self.assertEqual(first.candidate_bytes(), second.candidate_bytes())
        self.assertEqual(first.screening_manifest_bytes(), second.screening_manifest_bytes())
        self.assertEqual(first.frozen_trace_bytes(), second.frozen_trace_bytes())
        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(first.trace_id, second.trace_id)
        self.assertEqual(
            before,
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before},
        )

    def test_candidate_ties_have_an_explicit_threshold_order_and_trace_is_checked(self) -> None:
        _write_partition(
            self.root,
            2024,
            1,
            _frame([1, 2], [Decimal("0.000000000000000002"), Decimal("-0.000000000000000002")]),
        )

        outcome = screen_canonical_snapshot(
            self.root,
            ScreeningConfig("generic_screening_v1", (2, 0)),
        )

        manifest = outcome.screening_manifest
        self.assertEqual([item["threshold_units"] for item in manifest["candidate_metrics"]], [0, 2])
        self.assertEqual(outcome.candidate["threshold_units"], 0)
        self.assertEqual(manifest["trace_id"], outcome.trace_id)
        self.assertEqual(outcome.frozen_trace["candidate_id"], outcome.candidate_id)
        self.assertEqual(outcome.frozen_trace["snapshot_id"], outcome.snapshot_id)
        self.assertEqual(
            outcome.frozen_trace["frames"],
            [
                {
                    "expected_state_units": 2,
                    "operand_units": 2,
                    "sequence": 0,
                    "source_sequence": 0,
                },
                {
                    "expected_state_units": 0,
                    "operand_units": -2,
                    "sequence": 1,
                    "source_sequence": 1,
                },
            ],
        )

        candidate = outcome.candidate
        manifest = outcome.screening_manifest
        trace = outcome.frozen_trace
        self.assertEqual(
            candidate["candidate_id"],
            sha256_bytes(canonical_bytes({key: value for key, value in candidate.items() if key != "candidate_id"})),
        )
        self.assertEqual(
            manifest["screening_manifest_id"],
            sha256_bytes(
                canonical_bytes(
                    {key: value for key, value in manifest.items() if key != "screening_manifest_id"}
                )
            ),
        )
        self.assertEqual(
            trace["trace_id"],
            sha256_bytes(canonical_bytes({key: value for key, value in trace.items() if key != "trace_id"})),
        )
        self.assertEqual(manifest["selected_candidate_id"], candidate["candidate_id"])
        self.assertIn(candidate["candidate_id"], manifest["candidate_ids"])
        self.assertEqual(trace["candidate_id"], candidate["candidate_id"])
        self.assertEqual(trace["snapshot_id"], manifest["snapshot_id"])

    def test_decimal_conversion_is_exact_and_out_of_range_values_fail_closed(self) -> None:
        self.assertEqual(_decimal_to_scaled_i64(Decimal("0.000000000000000001")), 1)
        self.assertEqual(_decimal_to_scaled_i64(Decimal("-0.000000000000000001")), -1)
        with self.assertRaises(DatasetIntegrityError):
            _decimal_to_scaled_i64(Decimal("0.0000000000000000001"))
        with self.assertRaises(DatasetIntegrityError):
            _decimal_to_scaled_i64(Decimal("9223372036854775808"))
        with self.assertRaises(DatasetIntegrityError):
            _decimal_to_scaled_i64(1.0)
        _write_partition(
            self.root,
            2024,
            1,
            _frame([1], [Decimal("-9.223372036854775808")]),
        )
        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", (0,)))

    def test_invalid_config_empty_candidate_and_trace_cap_fail_closed(self) -> None:
        _write_partition(
            self.root,
            2024,
            1,
            _frame([1, 2, 3], [Decimal("0.000000000000000001")] * 3),
        )
        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", [1]))
        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", (1, 1)))
        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", (1.0,)))
        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", (-1,)))
        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", (4,)))
        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(
                self.root,
                ScreeningConfig("generic_screening_v1", (1,), trace_limit=2),
            )

    def test_absolute_score_accumulator_overflow_fails_closed(self) -> None:
        _write_partition(
            self.root,
            2024,
            1,
            _frame(
                [1, 2],
                [Decimal("9.000000000000000000"), Decimal("9.000000000000000000")],
            ),
        )

        with self.assertRaises(DatasetIntegrityError):
            screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", (0,)))

    def test_public_records_are_defensive_and_runtime_database_is_unchanged(self) -> None:
        paths = self._populate(self.root)
        runtime_database = ENGINE_ROOT / "runtime" / "experiments.sqlite3"
        before_database = (
            hashlib.sha256(runtime_database.read_bytes()).hexdigest()
            if runtime_database.is_file()
            else None
        )
        before_paths = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

        outcome = screen_canonical_snapshot(self.root, ScreeningConfig("generic_screening_v1", (2, 5)))
        exposed = outcome.screening_manifest
        exposed["row_count"] = 999
        exposed["candidate_ids"].clear()

        self.assertNotEqual(outcome.screening_manifest["row_count"], 999)
        self.assertTrue(outcome.screening_manifest["candidate_ids"])
        self.assertEqual(before_paths, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in paths})
        if before_database is not None:
            self.assertEqual(before_database, hashlib.sha256(runtime_database.read_bytes()).hexdigest())
