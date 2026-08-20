"""Deterministic, integer-only validation for D overfitting-safety evidence.

This module is deliberately pure: it performs no I/O, imports no runtime
engine code, and has no ambient clock, random source, or unordered iteration
in its verdict.  SQLite persistence and promotion gating live in ``registry``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .hashing import canonical_bytes, sha256_bytes


_PPM = 1_000_000
_POLICY_VERSION = 1


class OverfittingValidationError(ValueError):
    """Raised when D evidence cannot prove the required safety constraints."""


def _require_exact_keys(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise OverfittingValidationError(f"{label} has an unsupported shape")
    return value


def _require_int(value: object, label: str, *, minimum: int | None = None) -> int:
    if type(value) is not int:
        raise OverfittingValidationError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise OverfittingValidationError(f"{label} is below its minimum")
    return value


def _require_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise OverfittingValidationError(f"{label} must be a non-empty string")
    return value


def _list_of_ints(value: object, label: str, *, minimum: int | None = None) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise OverfittingValidationError(f"{label} must be an ordered integer list")
    return tuple(_require_int(item, f"{label}[{index}]", minimum=minimum) for index, item in enumerate(value))


@dataclass(frozen=True)
class OverfittingPolicy:
    """Explicit immutable D thresholds, all represented in integer units."""

    label_horizon_events: int
    alpha_ppm: int
    max_pbo_ppm: int
    min_fold_oos_score_bps: int
    min_regime_oos_score_bps: int
    min_neighbor_oos_score_bps: int
    max_parameter_drop_bps: int
    min_stressed_oos_score_bps: int
    required_regimes: tuple[str, ...]
    max_cscv_partitions: int = 32

    def __post_init__(self) -> None:
        _require_int(self.label_horizon_events, "label_horizon_events", minimum=1)
        _require_int(self.alpha_ppm, "alpha_ppm", minimum=1)
        if self.alpha_ppm > _PPM:
            raise OverfittingValidationError("alpha_ppm exceeds one")
        _require_int(self.max_pbo_ppm, "max_pbo_ppm", minimum=0)
        if self.max_pbo_ppm > _PPM:
            raise OverfittingValidationError("max_pbo_ppm exceeds one")
        for label, value in (
            ("min_fold_oos_score_bps", self.min_fold_oos_score_bps),
            ("min_regime_oos_score_bps", self.min_regime_oos_score_bps),
            ("min_neighbor_oos_score_bps", self.min_neighbor_oos_score_bps),
            ("min_stressed_oos_score_bps", self.min_stressed_oos_score_bps),
        ):
            _require_int(value, label)
        _require_int(self.max_parameter_drop_bps, "max_parameter_drop_bps", minimum=0)
        _require_int(self.max_cscv_partitions, "max_cscv_partitions", minimum=2)
        regimes = tuple(sorted(_require_text(item, "required_regimes") for item in self.required_regimes))
        if len(regimes) < 3 or len(set(regimes)) != len(regimes):
            raise OverfittingValidationError("required_regimes must contain at least three distinct regimes")
        object.__setattr__(self, "required_regimes", regimes)

    def to_payload(self) -> dict[str, Any]:
        return {
            "alpha_ppm": self.alpha_ppm,
            "label_horizon_events": self.label_horizon_events,
            "max_cscv_partitions": self.max_cscv_partitions,
            "max_parameter_drop_bps": self.max_parameter_drop_bps,
            "max_pbo_ppm": self.max_pbo_ppm,
            "min_fold_oos_score_bps": self.min_fold_oos_score_bps,
            "min_neighbor_oos_score_bps": self.min_neighbor_oos_score_bps,
            "min_regime_oos_score_bps": self.min_regime_oos_score_bps,
            "min_stressed_oos_score_bps": self.min_stressed_oos_score_bps,
            "required_regimes": list(self.required_regimes),
        }

    @classmethod
    def from_payload(cls, value: object) -> "OverfittingPolicy":
        item = _require_exact_keys(
            value,
            frozenset(
                {
                    "alpha_ppm",
                    "label_horizon_events",
                    "max_cscv_partitions",
                    "max_parameter_drop_bps",
                    "max_pbo_ppm",
                    "min_fold_oos_score_bps",
                    "min_neighbor_oos_score_bps",
                    "min_regime_oos_score_bps",
                    "min_stressed_oos_score_bps",
                    "required_regimes",
                }
            ),
            "policy",
        )
        regimes = item["required_regimes"]
        if not isinstance(regimes, list):
            raise OverfittingValidationError("required_regimes must be a list")
        return cls(
            label_horizon_events=_require_int(item["label_horizon_events"], "label_horizon_events", minimum=1),
            alpha_ppm=_require_int(item["alpha_ppm"], "alpha_ppm", minimum=1),
            max_pbo_ppm=_require_int(item["max_pbo_ppm"], "max_pbo_ppm", minimum=0),
            min_fold_oos_score_bps=_require_int(item["min_fold_oos_score_bps"], "min_fold_oos_score_bps"),
            min_regime_oos_score_bps=_require_int(item["min_regime_oos_score_bps"], "min_regime_oos_score_bps"),
            min_neighbor_oos_score_bps=_require_int(item["min_neighbor_oos_score_bps"], "min_neighbor_oos_score_bps"),
            max_parameter_drop_bps=_require_int(item["max_parameter_drop_bps"], "max_parameter_drop_bps", minimum=0),
            min_stressed_oos_score_bps=_require_int(item["min_stressed_oos_score_bps"], "min_stressed_oos_score_bps"),
            required_regimes=tuple(_require_text(entry, "required_regimes") for entry in regimes),
            max_cscv_partitions=_require_int(item["max_cscv_partitions"], "max_cscv_partitions", minimum=2),
        )


# D intentionally does not let a caller weaken safety thresholds inside an
# evidence payload.  The policy is part of the versioned, content-addressed
# contract; changing it requires a separately reviewed successor migration.
DEFAULT_POLICY = OverfittingPolicy(
    label_horizon_events=2,
    alpha_ppm=50_000,
    max_pbo_ppm=250_000,
    min_fold_oos_score_bps=0,
    min_regime_oos_score_bps=0,
    min_neighbor_oos_score_bps=0,
    max_parameter_drop_bps=25,
    min_stressed_oos_score_bps=0,
    required_regimes=("BEAR", "RANGE", "BULL"),
    max_cscv_partitions=32,
)


@dataclass(frozen=True)
class WalkForwardFold:
    """One chronological train/validation/OOS partition in event-index units."""

    train_start_event: int
    train_end_event: int
    validation_start_event: int
    validation_end_event: int
    test_start_event: int
    test_end_event: int
    purge_events: int
    embargo_events: int
    in_sample_score_bps: int
    out_of_sample_score_bps: int

    def to_payload(self) -> dict[str, int]:
        return {
            "embargo_events": self.embargo_events,
            "in_sample_score_bps": self.in_sample_score_bps,
            "out_of_sample_score_bps": self.out_of_sample_score_bps,
            "purge_events": self.purge_events,
            "test_end_event": self.test_end_event,
            "test_start_event": self.test_start_event,
            "train_end_event": self.train_end_event,
            "train_start_event": self.train_start_event,
            "validation_end_event": self.validation_end_event,
            "validation_start_event": self.validation_start_event,
        }

    @classmethod
    def from_payload(cls, value: object) -> "WalkForwardFold":
        item = _require_exact_keys(value, frozenset(cls(0, 0, 0, 0, 0, 0, 0, 0, 0, 0).to_payload()), "walk-forward fold")
        return cls(**{name: _require_int(entry, name) for name, entry in item.items()})


@dataclass(frozen=True)
class CscvPartition:
    """Deterministically ordered in-sample/OOS candidate-score vectors."""

    in_sample_scores_bps: tuple[int, ...]
    out_of_sample_scores_bps: tuple[int, ...]

    def to_payload(self) -> dict[str, list[int]]:
        return {
            "in_sample_scores_bps": list(self.in_sample_scores_bps),
            "out_of_sample_scores_bps": list(self.out_of_sample_scores_bps),
        }

    @classmethod
    def from_payload(cls, value: object) -> "CscvPartition":
        item = _require_exact_keys(value, frozenset({"in_sample_scores_bps", "out_of_sample_scores_bps"}), "CSCV partition")
        return cls(
            in_sample_scores_bps=_list_of_ints(item["in_sample_scores_bps"], "in_sample_scores_bps"),
            out_of_sample_scores_bps=_list_of_ints(item["out_of_sample_scores_bps"], "out_of_sample_scores_bps"),
        )


@dataclass(frozen=True)
class RegimeScore:
    """One named out-of-sample regime score."""

    regime_id: str
    out_of_sample_score_bps: int

    def to_payload(self) -> dict[str, Any]:
        return {"out_of_sample_score_bps": self.out_of_sample_score_bps, "regime_id": self.regime_id}

    @classmethod
    def from_payload(cls, value: object) -> "RegimeScore":
        item = _require_exact_keys(value, frozenset({"regime_id", "out_of_sample_score_bps"}), "regime")
        return cls(
            regime_id=_require_text(item["regime_id"], "regime_id"),
            out_of_sample_score_bps=_require_int(item["out_of_sample_score_bps"], "out_of_sample_score_bps"),
        )


@dataclass(frozen=True)
class OverfittingEvidence:
    """A complete D proof input; no caller-supplied pass/fail flag exists."""

    policy: OverfittingPolicy
    walk_forward_folds: tuple[WalkForwardFold, ...]
    raw_p_value_ppm: int
    cscv_partitions: tuple[CscvPartition, ...]
    regime_scores: tuple[RegimeScore, ...]
    center_oos_score_bps: int
    neighbor_oos_scores_bps: tuple[int, ...]
    baseline_cost_bps: int
    stressed_cost_bps: int
    stressed_oos_score_bps: int

    def to_input_payload(self) -> dict[str, Any]:
        return {
            "baseline_cost_bps": self.baseline_cost_bps,
            "center_oos_score_bps": self.center_oos_score_bps,
            "cscv_partitions": [item.to_payload() for item in self.cscv_partitions],
            "neighbor_oos_scores_bps": list(self.neighbor_oos_scores_bps),
            "policy": self.policy.to_payload(),
            "raw_p_value_ppm": self.raw_p_value_ppm,
            "regime_scores": [item.to_payload() for item in self.regime_scores],
            "stressed_cost_bps": self.stressed_cost_bps,
            "stressed_oos_score_bps": self.stressed_oos_score_bps,
            "walk_forward_folds": [item.to_payload() for item in self.walk_forward_folds],
        }

    @classmethod
    def from_input_payload(cls, value: object) -> "OverfittingEvidence":
        item = _require_exact_keys(
            value,
            frozenset(
                {
                    "baseline_cost_bps",
                    "center_oos_score_bps",
                    "cscv_partitions",
                    "neighbor_oos_scores_bps",
                    "policy",
                    "raw_p_value_ppm",
                    "regime_scores",
                    "stressed_cost_bps",
                    "stressed_oos_score_bps",
                    "walk_forward_folds",
                }
            ),
            "overfitting evidence",
        )
        folds = item["walk_forward_folds"]
        partitions = item["cscv_partitions"]
        regimes = item["regime_scores"]
        if not isinstance(folds, list) or not isinstance(partitions, list) or not isinstance(regimes, list):
            raise OverfittingValidationError("overfitting evidence collections must be lists")
        return cls(
            policy=OverfittingPolicy.from_payload(item["policy"]),
            walk_forward_folds=tuple(WalkForwardFold.from_payload(entry) for entry in folds),
            raw_p_value_ppm=_require_int(item["raw_p_value_ppm"], "raw_p_value_ppm", minimum=0),
            cscv_partitions=tuple(CscvPartition.from_payload(entry) for entry in partitions),
            regime_scores=tuple(RegimeScore.from_payload(entry) for entry in regimes),
            center_oos_score_bps=_require_int(item["center_oos_score_bps"], "center_oos_score_bps"),
            neighbor_oos_scores_bps=_list_of_ints(item["neighbor_oos_scores_bps"], "neighbor_oos_scores_bps"),
            baseline_cost_bps=_require_int(item["baseline_cost_bps"], "baseline_cost_bps", minimum=0),
            stressed_cost_bps=_require_int(item["stressed_cost_bps"], "stressed_cost_bps", minimum=0),
            stressed_oos_score_bps=_require_int(item["stressed_oos_score_bps"], "stressed_oos_score_bps"),
        )


def validate_and_canonicalize(evidence: OverfittingEvidence, deterministic_trial_count: int) -> dict[str, Any]:
    """Return canonical passing evidence or reject every incomplete/weak proof."""
    if not isinstance(evidence, OverfittingEvidence):
        raise OverfittingValidationError("evidence has an unsupported type")
    trial_count = _require_int(deterministic_trial_count, "deterministic_trial_count", minimum=1)
    policy = evidence.policy
    if policy.to_payload() != DEFAULT_POLICY.to_payload():
        raise OverfittingValidationError("overfitting evidence policy is not the bound D policy")
    folds = tuple(evidence.walk_forward_folds)
    if len(folds) < 3:
        raise OverfittingValidationError("at least three chronological walk-forward folds are required")
    previous_test_end: int | None = None
    for index, fold in enumerate(folds):
        values = (
            ("train_start_event", fold.train_start_event),
            ("train_end_event", fold.train_end_event),
            ("validation_start_event", fold.validation_start_event),
            ("validation_end_event", fold.validation_end_event),
            ("test_start_event", fold.test_start_event),
            ("test_end_event", fold.test_end_event),
            ("purge_events", fold.purge_events),
            ("embargo_events", fold.embargo_events),
            ("in_sample_score_bps", fold.in_sample_score_bps),
            ("out_of_sample_score_bps", fold.out_of_sample_score_bps),
        )
        for label, value in values:
            _require_int(value, f"walk_forward_folds[{index}].{label}", minimum=0 if label.endswith("event") or label.endswith("events") else None)
        if not (
            fold.train_start_event < fold.train_end_event <= fold.validation_start_event
            < fold.validation_end_event <= fold.test_start_event < fold.test_end_event
        ):
            raise OverfittingValidationError("walk-forward fold boundaries are not chronological")
        if fold.purge_events < policy.label_horizon_events or fold.embargo_events < policy.label_horizon_events:
            raise OverfittingValidationError("walk-forward purge/embargo is smaller than the label horizon")
        if fold.validation_start_event - fold.train_end_event < fold.purge_events:
            raise OverfittingValidationError("walk-forward purge gap is insufficient")
        if fold.test_start_event - fold.validation_end_event < fold.embargo_events:
            raise OverfittingValidationError("walk-forward embargo gap is insufficient")
        if fold.out_of_sample_score_bps < policy.min_fold_oos_score_bps:
            raise OverfittingValidationError("walk-forward out-of-sample score is below policy")
        if previous_test_end is not None and fold.test_start_event < previous_test_end:
            raise OverfittingValidationError("walk-forward OOS tests overlap")
        previous_test_end = fold.test_end_event

    raw_p = _require_int(evidence.raw_p_value_ppm, "raw_p_value_ppm", minimum=0)
    if raw_p > _PPM:
        raise OverfittingValidationError("raw_p_value_ppm exceeds one")
    corrected_p = raw_p * trial_count
    if corrected_p > policy.alpha_ppm:
        raise OverfittingValidationError("multiple-testing correction exceeds policy alpha")

    partitions = tuple(evidence.cscv_partitions)
    if len(partitions) < 2 or len(partitions) > policy.max_cscv_partitions:
        raise OverfittingValidationError("CSCV partition count is outside policy")
    candidate_count: int | None = None
    bad_partitions = 0
    for index, partition in enumerate(partitions):
        in_sample = _list_of_ints(partition.in_sample_scores_bps, f"cscv_partitions[{index}].in_sample_scores_bps")
        out_of_sample = _list_of_ints(partition.out_of_sample_scores_bps, f"cscv_partitions[{index}].out_of_sample_scores_bps")
        if len(in_sample) < 2 or len(in_sample) != len(out_of_sample):
            raise OverfittingValidationError("CSCV candidate scores have incompatible dimensions")
        if candidate_count is None:
            candidate_count = len(in_sample)
        elif candidate_count != len(in_sample):
            raise OverfittingValidationError("CSCV candidate universe changes between partitions")
        selected = max(range(len(in_sample)), key=lambda item: (in_sample[item], -item))
        ranked = sorted(range(len(out_of_sample)), key=lambda item: (out_of_sample[item], item))
        rank = ranked.index(selected) + 1
        if 2 * rank <= len(out_of_sample):
            bad_partitions += 1
    pbo_ppm = bad_partitions * _PPM // len(partitions)
    if pbo_ppm > policy.max_pbo_ppm:
        raise OverfittingValidationError("CSCV PBO exceeds policy")

    regimes = tuple(sorted(evidence.regime_scores, key=lambda item: item.regime_id))
    if tuple(item.regime_id for item in regimes) != policy.required_regimes:
        raise OverfittingValidationError("regime evidence does not exactly cover the required regimes")
    for regime in regimes:
        _require_int(regime.out_of_sample_score_bps, f"regime[{regime.regime_id}].out_of_sample_score_bps")
        if regime.out_of_sample_score_bps < policy.min_regime_oos_score_bps:
            raise OverfittingValidationError("a required regime score is below policy")

    center = _require_int(evidence.center_oos_score_bps, "center_oos_score_bps")
    neighbors = tuple(sorted(_list_of_ints(evidence.neighbor_oos_scores_bps, "neighbor_oos_scores_bps")))
    if len(neighbors) < 2:
        raise OverfittingValidationError("at least two parameter-neighborhood scores are required")
    if any(score < policy.min_neighbor_oos_score_bps for score in neighbors):
        raise OverfittingValidationError("a parameter-neighborhood score is below policy")
    if center - min(neighbors) > policy.max_parameter_drop_bps:
        raise OverfittingValidationError("parameter-neighborhood drop exceeds policy")

    baseline_cost = _require_int(evidence.baseline_cost_bps, "baseline_cost_bps", minimum=1)
    stressed_cost = _require_int(evidence.stressed_cost_bps, "stressed_cost_bps", minimum=1)
    stressed_score = _require_int(evidence.stressed_oos_score_bps, "stressed_oos_score_bps")
    if stressed_cost < 2 * baseline_cost:
        raise OverfittingValidationError("stressed cost is less than two times baseline cost")
    if stressed_score < policy.min_stressed_oos_score_bps:
        raise OverfittingValidationError("stressed out-of-sample score is below policy")

    policy_payload = policy.to_payload()
    return {
        "contract_version": _POLICY_VERSION,
        "cost_stress": {
            "baseline_cost_bps": baseline_cost,
            "stressed_cost_bps": stressed_cost,
            "stressed_oos_score_bps": stressed_score,
        },
        "cscv_partitions": [item.to_payload() for item in partitions],
        "multiple_testing": {
            "corrected_p_value_ppm": corrected_p,
            "raw_p_value_ppm": raw_p,
            "trial_count": trial_count,
        },
        "parameter_neighborhood": {
            "center_oos_score_bps": center,
            "neighbor_oos_scores_bps": list(neighbors),
        },
        "pbo": {
            "bad_partition_count": bad_partitions,
            "partition_count": len(partitions),
            "pbo_ppm": pbo_ppm,
        },
        "policy": policy_payload,
        "policy_sha256": sha256_bytes(canonical_bytes(policy_payload)),
        "regime_scores": [item.to_payload() for item in regimes],
        "walk_forward_folds": [item.to_payload() for item in folds],
    }


def validate_persisted_payload(value: object, deterministic_trial_count: int) -> dict[str, Any]:
    """Recompute a stored D verdict from its exact canonical evidence payload."""
    item = _require_exact_keys(
        value,
        frozenset(
            {
                "contract_version",
                "cost_stress",
                "cscv_partitions",
                "multiple_testing",
                "parameter_neighborhood",
                "pbo",
                "policy",
                "policy_sha256",
                "regime_scores",
                "walk_forward_folds",
            }
        ),
        "persisted overfitting assessment",
    )
    if item["contract_version"] != _POLICY_VERSION:
        raise OverfittingValidationError("overfitting assessment contract version is unsupported")
    multiple = _require_exact_keys(item["multiple_testing"], frozenset({"corrected_p_value_ppm", "raw_p_value_ppm", "trial_count"}), "multiple_testing")
    neighborhood = _require_exact_keys(item["parameter_neighborhood"], frozenset({"center_oos_score_bps", "neighbor_oos_scores_bps"}), "parameter_neighborhood")
    cost = _require_exact_keys(item["cost_stress"], frozenset({"baseline_cost_bps", "stressed_cost_bps", "stressed_oos_score_bps"}), "cost_stress")
    partitions = item["cscv_partitions"]
    regimes = item["regime_scores"]
    folds = item["walk_forward_folds"]
    if not isinstance(partitions, list) or not isinstance(regimes, list) or not isinstance(folds, list):
        raise OverfittingValidationError("persisted assessment collections must be lists")
    evidence = OverfittingEvidence(
        policy=OverfittingPolicy.from_payload(item["policy"]),
        walk_forward_folds=tuple(WalkForwardFold.from_payload(entry) for entry in folds),
        raw_p_value_ppm=_require_int(multiple["raw_p_value_ppm"], "raw_p_value_ppm", minimum=0),
        cscv_partitions=tuple(CscvPartition.from_payload(entry) for entry in partitions),
        regime_scores=tuple(RegimeScore.from_payload(entry) for entry in regimes),
        center_oos_score_bps=_require_int(neighborhood["center_oos_score_bps"], "center_oos_score_bps"),
        neighbor_oos_scores_bps=_list_of_ints(neighborhood["neighbor_oos_scores_bps"], "neighbor_oos_scores_bps"),
        baseline_cost_bps=_require_int(cost["baseline_cost_bps"], "baseline_cost_bps", minimum=1),
        stressed_cost_bps=_require_int(cost["stressed_cost_bps"], "stressed_cost_bps", minimum=1),
        stressed_oos_score_bps=_require_int(cost["stressed_oos_score_bps"], "stressed_oos_score_bps"),
    )
    recomputed = validate_and_canonicalize(evidence, deterministic_trial_count)
    if _require_int(multiple["trial_count"], "trial_count", minimum=1) != deterministic_trial_count:
        raise OverfittingValidationError("persisted assessment trial count is stale")
    if _require_int(multiple["corrected_p_value_ppm"], "corrected_p_value_ppm", minimum=0) != recomputed["multiple_testing"]["corrected_p_value_ppm"]:
        raise OverfittingValidationError("persisted corrected p-value does not match")
    pbo = _require_exact_keys(item["pbo"], frozenset({"bad_partition_count", "partition_count", "pbo_ppm"}), "pbo")
    if pbo != recomputed["pbo"]:
        raise OverfittingValidationError("persisted PBO does not match")
    if item["policy_sha256"] != recomputed["policy_sha256"]:
        raise OverfittingValidationError("persisted policy hash does not match")
    if canonical_bytes(item) != canonical_bytes(recomputed):
        raise OverfittingValidationError("persisted assessment is not canonical")
    return recomputed
