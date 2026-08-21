"""Deterministic, read-only generic screening over an R0 canonical snapshot."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import polars as pl

from .errors import DatasetIntegrityError
from .hashing import canonical_bytes, sha256_bytes, sha256_file
from .snapshot import materialize_canonical_snapshot


_SCREENING_SCHEMA_VERSION = "r1-vectorized-screening-v1"
_CANDIDATE_SCHEMA_VERSION = "r1-screening-candidate-v1"
_TRACE_SCHEMA_VERSION = "r1-frozen-simulation-trace-v1"
_DECIMAL_SCALE = 18
_I64_MIN = -(2**63)
_I64_MAX = 2**63 - 1
_STABLE_NAME = re.compile(r"[a-z][a-z0-9_-]{2,63}\Z")


@dataclass(frozen=True)
class ScreeningConfig:
    """Fixed, integer-only inputs for one deterministic screening pass."""

    strategy_family_id: str
    threshold_units: tuple[int, ...]
    trace_limit: int = 10_000


@dataclass(frozen=True)
class ScreeningOutcome:
    """Defensive canonical evidence emitted without filesystem or registry writes."""

    candidate_id: str
    screening_manifest_id: str
    snapshot_id: str
    trace_id: str
    _candidate_bytes: bytes
    _manifest_bytes: bytes
    _trace_bytes: bytes

    @property
    def candidate(self) -> dict[str, Any]:
        return _decode_object(self._candidate_bytes, "screening candidate")

    @property
    def screening_manifest(self) -> dict[str, Any]:
        return _decode_object(self._manifest_bytes, "screening manifest")

    @property
    def frozen_trace(self) -> dict[str, Any]:
        return _decode_object(self._trace_bytes, "frozen simulation trace")

    def candidate_bytes(self) -> bytes:
        return self._candidate_bytes

    def screening_manifest_bytes(self) -> bytes:
        return self._manifest_bytes

    def frozen_trace_bytes(self) -> bytes:
        return self._trace_bytes


def screen_canonical_snapshot(snapshot_root: Path, config: ScreeningConfig) -> ScreeningOutcome:
    """Screen one R0 snapshot through a descriptor-bound, integer-only path."""
    normalized = _validate_config(config)
    materialization = materialize_canonical_snapshot(snapshot_root)
    snapshot_id = materialization.snapshot.snapshot_id
    feature_rows = _feature_rows(materialization.frame)
    feature_sha256 = sha256_bytes(canonical_bytes(feature_rows))
    config_sha256 = sha256_bytes(canonical_bytes(normalized))
    code_sha256 = sha256_file(Path(__file__).resolve())

    features = _feature_frame(feature_rows)
    candidates, selected_rows = _screen_candidates(
        features,
        snapshot_id=snapshot_id,
        feature_sha256=feature_sha256,
        code_sha256=code_sha256,
        config_sha256=config_sha256,
        strategy_family_id=normalized["strategy_family_id"],
        thresholds=normalized["threshold_units"],
    )
    ranked = _rank_candidates(candidates)
    selected_candidate = ranked[0]
    chosen_rows = selected_rows[selected_candidate["candidate_id"]]
    trace = _build_frozen_trace(
        snapshot_id=snapshot_id,
        candidate_id=selected_candidate["candidate_id"],
        selected_rows=chosen_rows,
        trace_limit=normalized["trace_limit"],
    )
    trace_id = trace["trace_id"]

    manifest_material = {
        "candidate_ids": [candidate["candidate_id"] for candidate in ranked],
        "candidate_metrics": [
            {
                "candidate_id": candidate["candidate_id"],
                "rank": index,
                "score_units": candidate["score_units"],
                "selected_event_count": candidate["selected_event_count"],
                "threshold_units": candidate["threshold_units"],
            }
            for index, candidate in enumerate(ranked)
        ],
        "code_sha256": code_sha256,
        "config_sha256": config_sha256,
        "feature_sha256": feature_sha256,
        "row_count": len(feature_rows),
        "selected_candidate_id": selected_candidate["candidate_id"],
        "snapshot_id": snapshot_id,
        "strategy_family_id": normalized["strategy_family_id"],
        "trace_id": trace_id,
        "version": _SCREENING_SCHEMA_VERSION,
    }
    manifest_id = sha256_bytes(canonical_bytes(manifest_material))
    manifest_bytes = canonical_bytes(
        {"screening_manifest_id": manifest_id, **manifest_material}
    )

    trace_bytes = canonical_bytes(trace)
    candidate_bytes = canonical_bytes(selected_candidate)
    return ScreeningOutcome(
        candidate_id=selected_candidate["candidate_id"],
        screening_manifest_id=manifest_id,
        snapshot_id=snapshot_id,
        trace_id=trace_id,
        _candidate_bytes=candidate_bytes,
        _manifest_bytes=manifest_bytes,
        _trace_bytes=trace_bytes,
    )


def _validate_config(config: ScreeningConfig) -> dict[str, Any]:
    if not isinstance(config, ScreeningConfig):
        raise DatasetIntegrityError("screening configuration type is invalid")
    if not isinstance(config.strategy_family_id, str) or not _STABLE_NAME.fullmatch(
        config.strategy_family_id
    ):
        raise DatasetIntegrityError("screening strategy family identifier is invalid")
    if not isinstance(config.threshold_units, tuple) or not config.threshold_units:
        raise DatasetIntegrityError("screening thresholds must be a non-empty immutable tuple")
    thresholds = []
    for threshold in config.threshold_units:
        _require_i64(threshold, "screening threshold")
        if threshold < 0:
            raise DatasetIntegrityError("screening threshold must be non-negative")
        thresholds.append(threshold)
    if any(value in thresholds[:index] for index, value in enumerate(thresholds)):
        raise DatasetIntegrityError("screening thresholds must be unique")
    if not _is_exact_int(config.trace_limit) or not 1 <= config.trace_limit <= 10_000:
        raise DatasetIntegrityError("screening trace limit is invalid")
    return {
        "strategy_family_id": config.strategy_family_id,
        "threshold_units": sorted(thresholds),
        "trace_limit": config.trace_limit,
    }


def _feature_rows(frame: pl.DataFrame) -> list[dict[str, int]]:
    try:
        vectorized = (
            frame.select(
                [
                    pl.col("open_time").cast(pl.Int64).alias("open_time_us"),
                    (pl.col("close") - pl.col("open")).alias("delta_decimal"),
                ]
            )
            .sort("open_time_us")
        )
    except Exception as error:
        raise DatasetIntegrityError("canonical snapshot feature projection failed") from error
    if vectorized.height == 0:
        raise DatasetIntegrityError("canonical snapshot has no screening rows")
    if vectorized.schema["open_time_us"] != pl.Int64:
        raise DatasetIntegrityError("screening timestamps are not integer microseconds")

    timestamps = vectorized.get_column("open_time_us").to_list()
    decimals = vectorized.get_column("delta_decimal").to_list()
    rows = []
    previous_timestamp: Optional[int] = None
    for sequence, (timestamp, delta) in enumerate(zip(timestamps, decimals)):
        _require_i64(timestamp, "screening timestamp")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise DatasetIntegrityError("screening timestamps are not strictly ordered and unique")
        previous_timestamp = timestamp
        delta_units = _decimal_to_scaled_i64(delta)
        if delta_units == _I64_MIN:
            raise DatasetIntegrityError("screening delta cannot be represented as an absolute value")
        rows.append(
            {
                "delta_units": delta_units,
                "open_time_us": timestamp,
                "sequence": sequence,
            }
        )
    return rows


def _feature_frame(rows: list[dict[str, int]]) -> pl.DataFrame:
    try:
        frame = pl.DataFrame(
            {
                "delta_units": [row["delta_units"] for row in rows],
                "open_time_us": [row["open_time_us"] for row in rows],
                "sequence": [row["sequence"] for row in rows],
            },
            schema={
                "delta_units": pl.Int64,
                "open_time_us": pl.Int64,
                "sequence": pl.Int64,
            },
        ).with_columns(pl.col("delta_units").abs().alias("absolute_delta_units"))
    except Exception as error:
        raise DatasetIntegrityError("screening integer feature frame failed") from error
    if frame.get_column("absolute_delta_units").null_count() != 0:
        raise DatasetIntegrityError("screening absolute feature calculation is invalid")
    return frame.sort(["open_time_us", "sequence"])


def _screen_candidates(
    features: pl.DataFrame,
    *,
    snapshot_id: str,
    feature_sha256: str,
    code_sha256: str,
    config_sha256: str,
    strategy_family_id: str,
    thresholds: list[int],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, int]]]]:
    candidates: list[dict[str, Any]] = []
    selected_rows: dict[str, list[dict[str, int]]] = {}
    for threshold in thresholds:
        selected = features.filter(pl.col("absolute_delta_units") >= threshold).select(
            ["sequence", "open_time_us", "delta_units", "absolute_delta_units"]
        )
        if selected.height == 0:
            raise DatasetIntegrityError("screening threshold produced no deterministic candidate")
        rows = []
        score_units = 0
        for row in selected.iter_rows(named=True):
            absolute_delta_units = int(row["absolute_delta_units"])
            score_units = _checked_add_i64(score_units, absolute_delta_units)
            rows.append(
                {
                    "delta_units": int(row["delta_units"]),
                    "open_time_us": int(row["open_time_us"]),
                    "sequence": int(row["sequence"]),
                }
            )
        material = {
            "code_sha256": code_sha256,
            "config_sha256": config_sha256,
            "feature_sha256": feature_sha256,
            "score_units": score_units,
            "selected_event_count": len(rows),
            "snapshot_id": snapshot_id,
            "strategy_family_id": strategy_family_id,
            "threshold_units": threshold,
            "version": _CANDIDATE_SCHEMA_VERSION,
        }
        candidate_id = sha256_bytes(canonical_bytes(material))
        candidate = {"candidate_id": candidate_id, **material}
        candidates.append(candidate)
        selected_rows[candidate_id] = rows
    return candidates, selected_rows


def _rank_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not candidates:
        raise DatasetIntegrityError("screening produced no candidates")
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate["score_units"],
            -candidate["selected_event_count"],
            candidate["threshold_units"],
            candidate["candidate_id"],
        ),
    )


def _build_frozen_trace(
    *,
    snapshot_id: str,
    candidate_id: str,
    selected_rows: list[dict[str, int]],
    trace_limit: int,
) -> dict[str, Any]:
    if len(selected_rows) > trace_limit:
        raise DatasetIntegrityError("screening trace exceeds the fixed event cap")
    state_units = 0
    frames = []
    for expected_sequence, row in enumerate(selected_rows):
        if row["sequence"] < 0:
            raise DatasetIntegrityError("screening trace sequence is invalid")
        state_units = _checked_add_i64(state_units, row["delta_units"])
        frames.append(
            {
                "expected_state_units": state_units,
                "operand_units": row["delta_units"],
                "sequence": expected_sequence,
                "source_sequence": row["sequence"],
            }
        )
    material: dict[str, Any] = {
        "candidate_id": candidate_id,
        "frames": frames,
        "snapshot_id": snapshot_id,
        "version": _TRACE_SCHEMA_VERSION,
    }
    trace_id = sha256_bytes(canonical_bytes(material))
    return {"trace_id": trace_id, **material}


def _decimal_to_scaled_i64(value: Any) -> int:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DatasetIntegrityError("screening decimal feature is invalid")
    sign, digits, exponent = value.as_tuple()
    coefficient = int("".join(str(digit) for digit in digits)) if digits else 0
    exponent_shift = exponent + _DECIMAL_SCALE
    if exponent_shift >= 0:
        integer = coefficient * (10**exponent_shift)
    else:
        divisor = 10 ** (-exponent_shift)
        if coefficient % divisor != 0:
            raise DatasetIntegrityError("screening decimal loses fractional integer units")
        integer = coefficient // divisor
    if sign:
        integer = -integer
    _require_i64(integer, "screening decimal units")
    return integer


def _checked_add_i64(left: int, right: int) -> int:
    _require_i64(left, "screening accumulator")
    _require_i64(right, "screening operand")
    value = left + right
    _require_i64(value, "screening accumulator result")
    return value


def _require_i64(value: Any, label: str) -> None:
    if not _is_exact_int(value) or value < _I64_MIN or value > _I64_MAX:
        raise DatasetIntegrityError(f"{label} is outside the signed integer range")


def _is_exact_int(value: Any) -> bool:
    return type(value) is int


def _decode_object(raw: bytes, label: str) -> dict[str, Any]:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise DatasetIntegrityError(f"{label} canonical bytes are not an object")
    return value
