"""D1 engineering checks. Synthetic fixtures are never real research acceptance."""

from __future__ import annotations

import calendar
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))

import polars as pl

from research_engine import d1
from research_engine.errors import DatasetIntegrityError
from research_engine.hashing import canonical_bytes, sha256_bytes
from research_engine.snapshot import _EXPECTED_SCHEMA


def _bars(count: int = 960) -> tuple[d1.Bar, ...]:
    return tuple(d1.Bar(i*d1.HOUR_US, 10_000, 10_200) for i in range(count))


def _write_synthetic_corpus(root: Path) -> None:
    for year in (2024, 2025):
        for month in range(1, 13):
            start = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())*1_000_000
            n = calendar.monthrange(year, month)[1]*24
            ts = [start+i*d1.HOUR_US for i in range(n)]
            columns = {}
            for name, dtype in _EXPECTED_SCHEMA.items():
                if isinstance(dtype, pl.Decimal):
                    value = Decimal("61200") if name in ("close", "high") else Decimal("60000") if name in ("open", "low") else Decimal("1")
                    columns[name] = pl.Series([value]*n, dtype=dtype)
                elif name == "open_time":
                    columns[name] = pl.Series(ts, dtype=dtype)
                elif name == "close_time":
                    columns[name] = pl.Series([t+d1.HOUR_US-1 for t in ts], dtype=dtype)
                elif name == "trade_count":
                    columns[name] = pl.Series([1]*n, dtype=dtype)
                else:
                    value = {"schema_version": "1", "venue": "binance", "market_type": "spot", "symbol": "BTCUSDT", "interval": "1h"}.get(name, "SYNTHETIC_TEST_ONLY")
                    columns[name] = pl.Series([value]*n, dtype=dtype)
            target = root/f"year={year}"/f"month={month:02}"/"candles.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            pl.DataFrame(columns, schema=_EXPECTED_SCHEMA).write_parquet(target)


class D1EconomicTests(unittest.TestCase):
    def test_causal_entry_exit_and_known_economic_return(self) -> None:
        bars = list(_bars(60))
        bars = [d1.Bar(b.time_us, b.open_units, b.open_units) for b in bars]
        bars[24] = d1.Bar(bars[24].time_us, 10_000, 10_100)
        bars[27] = d1.Bar(bars[27].time_us, 11_000, 11_000)
        trades = d1._trades(tuple(bars), 50, 0, 60)
        self.assertEqual(len(trades), 1)
        trade = trades[0]
        self.assertEqual((trade.signal, trade.entry, trade.exit), (24, 25, 27))
        self.assertEqual(trade.gross_units, 10_000_000)
        self.assertEqual(trade.net_units, 9_760_000)
        self.assertEqual(d1._score(trades), 976)

    def test_future_prices_do_not_change_earlier_signal_or_trade(self) -> None:
        bars = _bars(80)
        before = d1._trades(bars, 50, 0, 50)
        mutated = tuple(b if i < 50 else d1.Bar(b.time_us, 9_000_000, 8_000_000) for i, b in enumerate(bars))
        self.assertEqual(before, d1._trades(mutated, 50, 0, 50))
        changed_exit = list(bars)
        changed_exit[27] = d1.Bar(bars[27].time_us, 20_000, 20_000)
        first = d1._trades(tuple(changed_exit), 50, 0, 50)[0]
        self.assertEqual((first.signal, first.entry), (before[0].signal, before[0].entry))
        self.assertNotEqual(first.gross_units, before[0].gross_units)

    def test_nonoverlap_and_fold_boundary_containment(self) -> None:
        trades = d1._trades(_bars(), 25, 50, 100)
        self.assertTrue(all(50 <= t.signal < t.entry < t.exit < 100 for t in trades))
        self.assertTrue(all(a.exit <= b.entry for a, b in zip(trades, trades[1:])))
        self.assertFalse(d1._trades(_bars(), 25, 50, 53))

    def test_cost_stress_preserves_fills_and_charges_exactly_double(self) -> None:
        ordinary = d1._trades(_bars(), 50, 0, 960)
        stress = d1._trades(_bars(), 50, 0, 960, 48)
        self.assertEqual(len(ordinary), len(stress))
        for a, b in zip(ordinary, stress):
            self.assertEqual((a.signal, a.entry, a.exit, a.gross_units), (b.signal, b.entry, b.exit, b.gross_units))
            self.assertEqual(a.net_units-b.net_units, 24*d1.UNITS_PER_BPS)

    def test_price_scale_does_not_silently_overflow_i64(self) -> None:
        self.assertEqual(d1._price_units(Decimal("61234.123456789123456789")), 61234123456789123456789)
        for value in (Decimal(0), Decimal(-1), Decimal("NaN"), Decimal("Infinity"), Decimal("0.0000000000000000001")):
            with self.subTest(value=value), self.assertRaises(DatasetIntegrityError):
                d1._price_units(value)

    def test_regime_uses_only_24_prior_hours(self) -> None:
        bars = list(_bars(50))
        for prior, expected in ((9000, "BULL"), (12000, "BEAR"), (10200, "RANGE")):
            bars[0] = d1.Bar(0, 10000, prior)
            self.assertEqual(d1._trades(tuple(bars), 50, 24, 28)[0].regime, expected)

    def test_exact_sign_null_includes_identity_ties_and_never_zero(self) -> None:
        result = d1._sign_pvalue((1,)*12)
        self.assertEqual(result, {"tail_count": 1, "transformation_count": 4096, "raw_p_value_ppm": 245})
        self.assertEqual(d1._sign_pvalue((0,)*12)["raw_p_value_ppm"], 1_000_000)
        self.assertEqual(d1._sign_pvalue((-1,)*12)["raw_p_value_ppm"], 1_000_000)
        self.assertEqual(d1._sign_pvalue((1, -1)*6)["tail_count"], 2510)
        for invalid in ((1,)*11, (True,)*12):
            with self.assertRaises(DatasetIntegrityError):
                d1._sign_pvalue(invalid)

    def test_cscv_all_twenty_complements_four_candidates_and_no_holdout(self) -> None:
        result = d1._calculate(_bars())
        combinations = result["cscv"]["partitions"]
        self.assertEqual(len(combinations), 20)
        self.assertEqual(len({tuple(x["in_sample_blocks"]) for x in combinations}), 20)
        for item in combinations:
            self.assertEqual(sorted(item["in_sample_blocks"]+item["out_of_sample_blocks"]), list(range(6)))
        for block in result["cscv"]["block_reports"]:
            self.assertEqual(len(block), 4)
            self.assertTrue(all(x["end"] <= result["holdout"]["start"] for x in block))
        for fold in result["derived_D_input"]["walk_forward_folds"]:
            self.assertEqual(fold["validation_start_event"]-fold["train_end_event"], 2)
            self.assertEqual(fold["test_start_event"]-fold["validation_end_event"], 2)

    def test_pbo_known_rank_and_percentage(self) -> None:
        good = d1.CscvPartition((40, 30, 20, 10), (40, 30, 20, 10))
        bad = d1.CscvPartition((40, 30, 20, 10), (10, 20, 30, 40))
        result = d1._pbo_diagnostic((good, bad)*10)
        self.assertEqual(result["partition_count"], 20)
        self.assertEqual(result["bad_partition_count"], 10)
        self.assertEqual(result["pbo_ppm"], 500_000)
        self.assertFalse(result["passed"])
        self.assertEqual([x["out_of_sample_rank_ascending"] for x in result["partition_ranks"][:2]], [4, 1])
        self.assertEqual(d1._pbo_diagnostic((good, good))["pbo_ppm"], 0)
        self.assertEqual(d1._pbo_diagnostic((bad, good, good))["pbo_ppm"], 333_333)

    def test_pbo_ties_match_existing_D_stable_index_rule(self) -> None:
        # IS tie selects the first candidate. OOS ties rank index0 lowest.
        tied = d1.CscvPartition((10, 10, 10, 10), (1, 1, 1, 1))
        best = d1.CscvPartition((10, 10, 0, 0), (4, 1, 2, 3))
        result = d1._pbo_diagnostic((tied, best))
        self.assertEqual([x["selected_candidate_index"] for x in result["partition_ranks"]], [0, 0])
        self.assertEqual([x["out_of_sample_rank_ascending"] for x in result["partition_ranks"]], [1, 4])
        self.assertEqual(result["pbo_ppm"], 500_000)
        for invalid in ((tied,), (d1.CscvPartition((1, 2), (1, 2)),)*2):
            with self.assertRaises(DatasetIntegrityError):
                d1._pbo_diagnostic(invalid)

    def test_bad_economics_is_not_hidden_by_engineering_success(self) -> None:
        first = d1._calculate(_bars())
        second = d1._calculate(_bars())
        self.assertEqual(canonical_bytes(first), canonical_bytes(second))
        self.assertTrue(first["implementation_pass"])
        self.assertFalse(first["existing_D_gate"]["passed"])
        self.assertNotEqual(first["strategy_verdict"], "CONDITIONAL_NUMERIC_PASS")
        self.assertTrue(all(value is False for value in first["authority"].values()))
        self.assertLess(first["holdout"]["stress"]["score_bps"], 0)
        self.assertEqual(first["significance"]["corrected_p_value_ppm"], first["significance"]["raw_p_value_ppm"]*4)
        self.assertEqual(first["pbo"]["partition_count"], 20)
        self.assertFalse(first["gate_diagnostics"]["all_fold_oos_nonnegative"])
        self.assertFalse(first["gate_diagnostics"]["double_cost_stress_nonnegative"])

    def test_empty_trade_sets_never_receive_strategy_acceptance(self) -> None:
        bars = tuple(d1.Bar(b.time_us, b.open_units, b.open_units) for b in _bars())
        result = d1._calculate(bars)
        self.assertEqual(result["strategy_verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertTrue(result["insufficient_evidence"])

    def test_frozen_simulation_parameters_reject_changes(self) -> None:
        for threshold, cost in ((26, 24), (True, 24), (25, 0), (25, 23)):
            with self.assertRaises(DatasetIntegrityError):
                d1._trades(_bars(), threshold, 0, 900, cost)

    def test_missing_holdout_candidate_cannot_be_counted_as_robust_zero(self) -> None:
        bars = tuple(b if i < 768 else d1.Bar(b.time_us, b.open_units, 10_075)
                     for i, b in enumerate(_bars()))
        result = d1._calculate(bars)
        self.assertIn("holdout_threshold_100_insufficient_trades", result["insufficient_evidence"])
        self.assertEqual(result["strategy_verdict"], "INSUFFICIENT_EVIDENCE")


class D1CanonicalAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)/"synthetic-test-only"
        _write_synthetic_corpus(cls.root)
        cls.frozen = d1.freeze_method(cls.root)
        cls.digest = sha256_bytes(cls.frozen)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def test_freeze_inventories_without_computing_returns(self) -> None:
        with mock.patch.object(d1, "_calculate", side_effect=AssertionError("economic read before seal")):
            self.assertEqual(d1.freeze_method(self.root), self.frozen)
        method = json.loads(self.frozen)
        self.assertEqual(method["corpus"]["row_count"], 17544)
        self.assertEqual(method["method"]["candidate_thresholds_bps"], [25, 50, 75, 100])

    def test_complete_canonical_roundtrip_is_deterministic_and_read_only(self) -> None:
        before = {p: p.read_bytes() for p in self.root.rglob("*.parquet")}
        first = d1.evaluate(self.root, self.frozen, self.digest)
        second = d1.evaluate(self.root, self.frozen, self.digest)
        self.assertEqual(first, second)
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*.parquet")})
        result = json.loads(first)
        self.assertTrue(result["implementation_pass"])
        self.assertEqual(result["row_count"], 17544)
        self.assertEqual(result["strategy_verdict"], "INSUFFICIENT_EVIDENCE")

    def test_independent_method_hash_and_frozen_parameters_required(self) -> None:
        with self.assertRaises(DatasetIntegrityError):
            d1.evaluate(self.root, self.frozen, "0"*64)
        changed = json.loads(self.frozen)
        changed["method"]["roundtrip_cost_bps"] = 1
        raw = canonical_bytes(changed)
        with self.assertRaises(DatasetIntegrityError):
            d1.evaluate(self.root, raw, sha256_bytes(raw))
        with self.assertRaises(DatasetIntegrityError):
            d1._strict_object(b'{"a":1,"a":2}')

    def test_changed_source_identity_rejects_before_computation(self) -> None:
        with mock.patch.object(d1, "_code_sha", return_value="0"*64), mock.patch.object(d1, "_calculate", side_effect=AssertionError("must reject early")):
            with self.assertRaises(DatasetIntegrityError):
                d1.evaluate(self.root, self.frozen, self.digest)

    def test_mutation_during_calculation_rejects_evidence(self) -> None:
        with mock.patch.object(d1, "freeze_method", side_effect=[self.frozen, self.frozen+b" "]):
            with self.assertRaises(DatasetIntegrityError):
                d1.evaluate(self.root, self.frozen, self.digest)

    def test_replaced_partition_is_detected(self) -> None:
        target = self.root/"year=2024"/"month=01"/"candles.parquet"
        original = target.read_bytes()
        try:
            target.write_bytes(b"not parquet")
            with self.assertRaises(DatasetIntegrityError):
                d1.evaluate(self.root, self.frozen, self.digest)
        finally:
            target.write_bytes(original)

    def test_missing_month_and_incorrect_series_are_rejected(self) -> None:
        manifest = json.loads(self.frozen)["corpus"]
        manifest["series"]["interval"] = "1m"
        with self.assertRaises(DatasetIntegrityError):
            d1._check_manifest(manifest)
        manifest = json.loads(self.frozen)["corpus"]
        manifest["partitions"].pop()
        with self.assertRaises(DatasetIntegrityError):
            d1._check_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
