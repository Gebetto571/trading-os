"""Frozen, research-only economic evidence from a canonical BTCUSDT corpus.

This is a new bounded hypothesis, not the old R1 absolute-movement trace.
It never writes a database, promotes a strategy, or grants trading authority.
The sign-flip inference is conditional on block-wise null sign invariance;
market observations alone do not establish that assumption.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import polars as pl

from .errors import DatasetIntegrityError
from .hashing import canonical_bytes, required_regular_file, selected_tree_sha256, sha256_bytes
from .overfitting import (
    DEFAULT_POLICY, CscvPartition, OverfittingEvidence, OverfittingValidationError,
    RegimeScore, WalkForwardFold, validate_and_canonicalize,
)
from .snapshot import build_canonical_snapshot, materialize_canonical_snapshot

HOUR_US = 3_600_000_000
START_US = 1_704_067_200_000_000  # 2024-01-01T00:00:00Z
END_US = 1_767_225_600_000_000  # 2026-01-01T00:00:00Z
RETURN_SCALE = 100_000_000
UNITS_PER_BPS = RETURN_SCALE // 10_000
THRESHOLDS = (25, 50, 75, 100)
CENTER = 50
COST_BPS = 24
STRESS_BPS = 48
P_BLOCKS = 12
MIN_TRADES = 10


def method_spec() -> dict[str, Any]:
    """Return the complete fixed method before any economic evaluation."""
    return {
        "version": "d1-causal-impulse-v1",
        "hypothesis": "long after a positive one-hour candle; fixed two-hour holding",
        "series": {"venue": "binance", "market_type": "spot", "symbol": "BTCUSDT", "interval": "1h"},
        "start_us_inclusive": START_US, "end_us_exclusive": END_US,
        "candidate_thresholds_bps": list(THRESHOLDS), "fixed_center_threshold_bps": CENTER,
        "neighbor_thresholds_bps": [25, 75], "declared_family_trial_count": 4,
        "signal": "(close[t]-open[t])*10000 >= threshold*open[t]",
        "entry": "open[t+1]", "exit": "open[t+3]", "overlap": "forbidden",
        "return": "floor((exit-entry)*100000000/entry) minus roundtrip costs; fixed unit notional; no compounding",
        "score": "floor(sum(net_return_units)/10000), including zero-exposure hours on a common time index",
        "roundtrip_cost_bps": COST_BPS, "stressed_roundtrip_cost_bps": STRESS_BPS,
        "cost_assumption": "10bps fee and 2bps slippage per side; assumptions, not verified account fees or fills",
        "regime": "close[t]/close[t-24]-1 >=100bps BULL, <=-100bps BEAR, otherwise RANGE; known at signal time",
        "development": "first floor(4*N/5) rows; final remainder is holdout",
        "walk_forward": "u=floor(development/8); train[0,2u/4u/6u), validation[train_end+2,(3/5/7)u), test[validation_end+2,(4/6/8)u); three fixed-center folds",
        "boundary": "reset positions per segment; signal, entry, exit all inside segment; only past regime lookback allowed",
        "cscv": "six equal consecutive development blocks; exclude final development remainder; all20 combinations of3 blocks; four fixed candidates; sum common-index returns",
        "pbo_ties": "existing D v1: lower candidate index wins IS tie; stable ascending index breaks OOS ties",
        "pvalue": "holdout split into12 equal chronological blocks; final remainder excluded; all4096 sign transformations including identity; one-sided >= tail; ceil ppm",
        "pvalue_assumption": "under null, joint block PnL distribution is invariant under independent block sign reversals; not established by this report",
        "pvalue_correction": "existing D Bonferroni x4; no hidden tested alternatives permitted",
        "minimum_trades": MIN_TRADES,
        "minimum_scope": "each candidate in each CSCV block and whole holdout; center in every fold train/test and each holdout regime; every sign block must contain a trade",
        "holdout_policy": "one frozen method, no tuning after outcomes; identical rerun is verification only; new method requires new study and independent future holdout",
        "gate_policy": DEFAULT_POLICY.to_payload(),
        "authority": {"paper": False, "live": False, "promotion": False, "registry_write": False},
        "sources": ["https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf", "https://arxiv.org/html/1411.7565"],
    }


def _code_sha() -> str:
    root = Path(__file__).resolve().parent
    return selected_tree_sha256(root, [Path(p) for p in ("d1.py", "snapshot.py", "hashing.py", "overfitting.py", "errors.py")])


def _check_manifest(manifest: dict[str, Any]) -> None:
    if manifest["series"] != method_spec()["series"]:
        raise DatasetIntegrityError("D1 requires Binance spot BTCUSDT 1h")
    if (manifest["first_open_time_us"], manifest["last_open_time_us"], manifest["row_count"]) != (START_US, END_US-HOUR_US, (END_US-START_US)//HOUR_US):
        raise DatasetIntegrityError("D1 requires exactly the complete 2024-2025 hourly corpus")
    expected = [f"year={year}/month={month:02}/candles.parquet" for year in (2024, 2025) for month in range(1, 13)]
    if [p["path"] for p in manifest["partitions"]] != expected:
        raise DatasetIntegrityError("D1 requires all24 canonical monthly partitions")


def freeze_method(snapshot_root: Path) -> bytes:
    """Inventory only; no signal, return, selection, or significance calculation."""
    snapshot = build_canonical_snapshot(snapshot_root)
    _check_manifest(snapshot.manifest)
    return canonical_bytes({"method": method_spec(), "corpus": snapshot.manifest,
                            "snapshot_id": snapshot.snapshot_id, "code_sha256": _code_sha(),
                            "polars_version": pl.__version__})


def _strict_object(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise DatasetIntegrityError("D1 method is not JSON") from error
    if not isinstance(value, dict) or canonical_bytes(value) != raw:
        raise DatasetIntegrityError("D1 method must be exact canonical JSON without duplicate keys")
    return value


def _price_units(value: Decimal) -> int:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise DatasetIntegrityError("D1 prices must be positive finite decimal values")
    sign, digits, exponent = value.as_tuple()
    coefficient = int("".join(map(str, digits)))
    shift = exponent + 18
    if sign or shift < 0:
        raise DatasetIntegrityError("D1 price has unsupported precision")
    return coefficient * 10**shift


@dataclass(frozen=True)
class Bar:
    time_us: int
    open_units: int
    close_units: int


@dataclass(frozen=True)
class Trade:
    signal: int
    entry: int
    exit: int
    gross_units: int
    net_units: int
    regime: str

    def payload(self) -> dict[str, Any]:
        return dict(signal=self.signal, entry=self.entry, exit=self.exit,
                    gross_units=self.gross_units, net_units=self.net_units, regime=self.regime)


def _trades(bars: tuple[Bar, ...], threshold: int, start: int, end: int, cost_bps: int = COST_BPS) -> tuple[Trade, ...]:
    if type(threshold) is not int or threshold not in THRESHOLDS or type(cost_bps) is not int or cost_bps not in (COST_BPS, STRESS_BPS):
        raise DatasetIntegrityError("D1 simulation parameters are frozen")
    if not 0 <= start < end <= len(bars):
        raise DatasetIntegrityError("D1 segment is invalid")
    trades = []
    next_entry = start
    for t in range(max(start, 24), end-3):
        bar = bars[t]
        if t+1 < next_entry or (bar.close_units-bar.open_units)*10_000 < threshold*bar.open_units:
            continue
        entry = bars[t+1].open_units
        gross = (bars[t+3].open_units-entry)*RETURN_SCALE // entry
        past = bars[t-24].close_units
        change = (bar.close_units-past)*10_000
        regime = "BULL" if change >= 100*past else "BEAR" if change <= -100*past else "RANGE"
        trades.append(Trade(t, t+1, t+3, gross, gross-cost_bps*UNITS_PER_BPS, regime))
        next_entry = t+3
    return tuple(trades)


def _score(trades: tuple[Trade, ...]) -> int:
    return sum(t.net_units for t in trades) // UNITS_PER_BPS


def _summary(trades: tuple[Trade, ...], start: int, end: int) -> dict[str, Any]:
    return {"start": start, "end": end, "trade_count": len(trades), "score_bps": _score(trades),
            "net_return_units": sum(t.net_units for t in trades),
            "trades_sha256": sha256_bytes(canonical_bytes([t.payload() for t in trades]))}


def _sign_pvalue(blocks: tuple[int, ...]) -> dict[str, int]:
    if len(blocks) != P_BLOCKS or any(type(v) is not int for v in blocks):
        raise DatasetIntegrityError("D1 pvalue requires12 integer blocks")
    observed = sum(blocks)
    total = 2**P_BLOCKS
    tail = sum(sum(value if mask & (1 << index) else -value
                   for index, value in enumerate(blocks)) >= observed
               for mask in range(total))
    return {"tail_count": tail, "transformation_count": total,
            "raw_p_value_ppm": (tail*1_000_000 + total-1)//total}


def _pbo_diagnostic(partitions: tuple[CscvPartition, ...]) -> dict[str, Any]:
    """Report D v1's exact selection/rank rule even if an earlier gate rejects.

    The public D validator returns only on a wholly passing proof, so it cannot
    supply this diagnostic on rejection.  Its tie handling and integer rounding
    are preserved here; this report never substitutes for that validator.
    """
    if not 2 <= len(partitions) <= DEFAULT_POLICY.max_cscv_partitions:
        raise DatasetIntegrityError("D1 CSCV partition count is invalid")
    ranks = []
    bad = 0
    for partition in partitions:
        inside, outside = partition.in_sample_scores_bps, partition.out_of_sample_scores_bps
        if len(inside) != len(THRESHOLDS) or len(outside) != len(THRESHOLDS) or any(type(v) is not int for v in inside+outside):
            raise DatasetIntegrityError("D1 CSCV requires four integer candidate scores")
        selected = max(range(len(inside)), key=lambda i: (inside[i], -i))
        ordered = sorted(range(len(outside)), key=lambda i: (outside[i], i))
        rank = ordered.index(selected)+1
        is_bad = 2*rank <= len(outside)
        bad += int(is_bad)
        ranks.append({"selected_candidate_index": selected, "selected_threshold_bps": THRESHOLDS[selected],
                      "out_of_sample_rank_ascending": rank, "below_median": is_bad})
    ppm = bad*1_000_000//len(partitions)
    return {"bad_partition_count": bad, "partition_count": len(partitions), "pbo_ppm": ppm,
            "maximum_pbo_ppm": DEFAULT_POLICY.max_pbo_ppm,
            "passed": ppm <= DEFAULT_POLICY.max_pbo_ppm, "partition_ranks": ranks}


def _calculate(bars: tuple[Bar, ...]) -> dict[str, Any]:
    """Pure economic study; tests may supply synthetic bars, not real acceptance."""
    n = len(bars)
    dev_end = 4*n//5
    if n < 720:
        raise DatasetIntegrityError("D1 corpus is too small for bounded partitions")
    reasons: list[str] = []
    folds = []
    fold_reports = []
    u = dev_end//8
    for index in range(3):
        train_end, val_end, test_end = (2+2*index)*u, (3+2*index)*u, (4+2*index)*u
        train = _trades(bars, CENTER, 0, train_end)
        validation = _trades(bars, CENTER, train_end+2, val_end)
        test = _trades(bars, CENTER, val_end+2, test_end)
        if min(len(train), len(test)) < MIN_TRADES:
            reasons.append(f"fold_{index}_trade_count_below_{MIN_TRADES}")
        folds.append(WalkForwardFold(0, train_end, train_end+2, val_end, val_end+2, test_end, 2, 2, _score(train), _score(test)))
        fold_reports.append({"train": _summary(train, 0, train_end), "validation": _summary(validation, train_end+2, val_end), "test": _summary(test, val_end+2, test_end)})

    width = dev_end//6
    cscv_blocks = []
    cscv_units = []
    for block in range(6):
        start, end = block*width, (block+1)*width
        candidates = [_trades(bars, threshold, start, end) for threshold in THRESHOLDS]
        for threshold, trades in zip(THRESHOLDS, candidates):
            if len(trades) < MIN_TRADES:
                reasons.append(f"cscv_block_{block}_threshold_{threshold}_insufficient_trades")
        cscv_blocks.append([_summary(trades, start, end) for trades in candidates])
        cscv_units.append([sum(t.net_units for t in trades) for trades in candidates])
    partitions = []
    partition_indices = []
    triples = ((a, b, c) for a in range(4) for b in range(a+1, 5) for c in range(b+1, 6))
    for chosen in triples:
        complement = tuple(i for i in range(6) if i not in chosen)
        partitions.append(CscvPartition(
            tuple(sum(cscv_units[i][c] for i in chosen)//UNITS_PER_BPS for c in range(4)),
            tuple(sum(cscv_units[i][c] for i in complement)//UNITS_PER_BPS for c in range(4))))
        partition_indices.append({"in_sample_blocks": list(chosen), "out_of_sample_blocks": list(complement)})

    holdout = {threshold: _trades(bars, threshold, dev_end, n) for threshold in THRESHOLDS}
    center = holdout[CENTER]
    for threshold in THRESHOLDS:
        if len(holdout[threshold]) < MIN_TRADES:
            reasons.append(f"holdout_threshold_{threshold}_insufficient_trades")
    regimes = []
    regime_reports = []
    for regime in DEFAULT_POLICY.required_regimes:
        trades = tuple(t for t in center if t.regime == regime)
        if len(trades) < MIN_TRADES:
            reasons.append(f"holdout_{regime}_insufficient_trades")
        regimes.append(RegimeScore(regime, _score(trades)))
        regime_reports.append({"regime": regime, **_summary(trades, dev_end, n)})
    stressed = _trades(bars, CENTER, dev_end, n, STRESS_BPS)
    pwidth = (n-dev_end)//P_BLOCKS
    pblocks = []
    preports = []
    for block in range(P_BLOCKS):
        start, end = dev_end+block*pwidth, dev_end+(block+1)*pwidth
        trades = _trades(bars, CENTER, start, end)
        if not trades:
            reasons.append(f"pvalue_block_{block}_has_no_trades")
        pblocks.append(sum(t.net_units for t in trades))
        preports.append(_summary(trades, start, end))
    significance = _sign_pvalue(tuple(pblocks))
    pbo = _pbo_diagnostic(tuple(partitions))
    evidence = OverfittingEvidence(DEFAULT_POLICY, tuple(folds), significance["raw_p_value_ppm"], tuple(partitions),
                                  tuple(regimes), _score(center), tuple(_score(holdout[t]) for t in (25, 75)),
                                  COST_BPS, STRESS_BPS, _score(stressed))
    canonical_gate = None
    gate_error = None
    try:
        canonical_gate = validate_and_canonicalize(evidence, len(THRESHOLDS))
    except OverfittingValidationError as error:
        gate_error = str(error)
    verdict = "INSUFFICIENT_EVIDENCE" if reasons else "REJECT" if gate_error else "CONDITIONAL_NUMERIC_PASS"
    diagnostics = {
        "sample_coverage": not reasons,
        "all_fold_oos_nonnegative": all(f.out_of_sample_score_bps >= DEFAULT_POLICY.min_fold_oos_score_bps for f in folds),
        "bonferroni_significance": significance["raw_p_value_ppm"]*len(THRESHOLDS) <= DEFAULT_POLICY.alpha_ppm,
        "pbo": pbo["passed"],
        "all_regimes_nonnegative": all(r.out_of_sample_score_bps >= DEFAULT_POLICY.min_regime_oos_score_bps for r in regimes),
        "both_neighbors_nonnegative": all(s >= DEFAULT_POLICY.min_neighbor_oos_score_bps for s in evidence.neighbor_oos_scores_bps),
        "neighbor_drop_within_limit": evidence.center_oos_score_bps-min(evidence.neighbor_oos_scores_bps) <= DEFAULT_POLICY.max_parameter_drop_bps,
        "double_cost_stress_nonnegative": _score(stressed) >= DEFAULT_POLICY.min_stressed_oos_score_bps,
    }
    return {"implementation_pass": True, "strategy_verdict": verdict, "insufficient_evidence": reasons,
            "gate_diagnostics": diagnostics, "pbo": pbo,
            "existing_D_gate": {"passed": gate_error is None, "error": gate_error, "canonical_passed_payload": canonical_gate},
            "derived_D_input": evidence.to_input_payload(), "walk_forward": fold_reports,
            "cscv": {"block_reports": cscv_blocks, "partitions": partition_indices, "excluded_tail_rows": dev_end-6*width},
            "holdout": {"start": dev_end, "end": n, "candidates": [{"threshold_bps": t, **_summary(holdout[t], dev_end, n)} for t in THRESHOLDS],
                        "regimes": regime_reports, "stress": _summary(stressed, dev_end, n)},
            "significance": {**significance, "blocks": preports, "excluded_tail_rows": n-dev_end-P_BLOCKS*pwidth,
                             "bonferroni_trial_count": 4, "corrected_p_value_ppm": significance["raw_p_value_ppm"]*4},
            "authority": method_spec()["authority"],
            "limitations": [method_spec()["pvalue_assumption"], method_spec()["cost_assumption"],
                            "No H1 registry promotion or reusable C3 transport is claimed.",
                            "Four predeclared trials cover this new family only, not undisclosed prior research.",
                            "This report cannot prove that supplied market bytes came from the operator's canonical database."]}


def evaluate(snapshot_root: Path, method_raw: bytes, expected_method_sha256: str) -> bytes:
    if sha256_bytes(method_raw) != expected_method_sha256:
        raise DatasetIntegrityError("D1 frozen method SHA-256 mismatch")
    method = _strict_object(method_raw)
    if freeze_method(snapshot_root) != method_raw:
        raise DatasetIntegrityError("D1 corpus, code, dependency or frozen method changed")
    materialization = materialize_canonical_snapshot(snapshot_root)
    if materialization.snapshot.snapshot_id != method["snapshot_id"]:
        raise DatasetIntegrityError("D1 corpus changed during materialization")
    frame = materialization.frame
    timestamps = frame.get_column("open_time").cast(pl.Int64).to_list()
    if timestamps != list(range(START_US, END_US, HOUR_US)):
        raise DatasetIntegrityError("D1 hourly chronology is incomplete")
    bars = tuple(Bar(t, _price_units(o), _price_units(c)) for t, o, c in zip(timestamps, frame.get_column("open").to_list(), frame.get_column("close").to_list()))
    result = _calculate(bars)
    # Preserve a before/after seal even when an input is replaced during calculation.
    if freeze_method(snapshot_root) != method_raw:
        raise DatasetIntegrityError("D1 corpus or source changed during evaluation")
    result.update({"version": "d1-real-output-evidence-v1", "method_sha256": expected_method_sha256,
                   "snapshot_id": method["snapshot_id"], "code_sha256": method["code_sha256"],
                   "row_count": len(bars), "method": method["method"]})
    return canonical_bytes(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Frozen research-only D1 evidence; no database or trading writes")
    parser.add_argument("action", choices=("freeze", "evaluate"))
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--method", type=Path)
    parser.add_argument("--method-sha256")
    args = parser.parse_args()
    try:
        if args.action == "freeze":
            if args.method or args.method_sha256:
                raise DatasetIntegrityError("freeze does not accept a method override")
            output = freeze_method(args.snapshot_root)
        else:
            if not args.method or not args.method_sha256:
                raise DatasetIntegrityError("evaluate requires a frozen method file and independent SHA-256")
            output = evaluate(args.snapshot_root, required_regular_file(args.method, "D1 method").read_bytes(), args.method_sha256)
    except (DatasetIntegrityError, OSError) as error:
        print(json.dumps({"implementation_pass": False, "error": str(error), "authority": method_spec()["authority"]}, sort_keys=True))
        return 2
    # No newline: these are the exact bytes sealed by --method-sha256.
    print(output.decode("ascii"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
