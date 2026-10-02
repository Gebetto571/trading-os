"""Read-only Polars event study with deterministic identities and local registry."""

from __future__ import annotations

import os
import platform
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from .config import EngineConfig, load_config
from .errors import ConfigError, DatasetIntegrityError
from .hashing import canonical_bytes, selected_tree_sha256, sha256_bytes, sha256_file
from .registry import ExperimentRegistry


_ENGINE_SCHEMA_VERSION = "research-engine-a0-v1"
_REQUIRED_COLUMNS = ("open_time", "open", "close")


@dataclass(frozen=True)
class DatasetSnapshot:
    """Validated input metadata and the one materialized research frame."""

    path: Path
    sha256: str
    identity: str
    row_count: int
    schema: dict[str, str]
    frame: pl.DataFrame


@dataclass(frozen=True)
class RunOutcome:
    """The public result separates stable evidence from observational telemetry."""

    canonical_summary: dict[str, Any]
    result_artifact_id: str
    reused_registry_result: bool
    telemetry: dict[str, Any]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "canonical_summary": self.canonical_summary,
            "registry": {"reused_completed_result": self.reused_registry_result},
            "result_artifact_id": self.result_artifact_id,
            "telemetry": self.telemetry,
        }


def run_experiment(config_path: Path) -> RunOutcome:
    """Run one fully isolated A0 study without writing the canonical dataset."""
    config = load_config(config_path)
    started_at_ns = time.time_ns()
    started_perf_ns = time.perf_counter_ns()

    snapshot = _load_dataset(config)
    engine_root = _engine_root()
    code_sha256 = _code_sha256(engine_root)
    identity_inputs = {
        "code_sha256": code_sha256,
        "config_sha256": config.raw_sha256,
        "dataset_identity": snapshot.identity,
        "dataset_sha256": snapshot.sha256,
        "engine_schema_version": _ENGINE_SCHEMA_VERSION,
        "strategy_family_id": config.strategy_family_id,
        "trial_id": config.trial_id,
    }
    experiment_id = sha256_bytes(canonical_bytes(identity_inputs))
    event_study = _event_study(snapshot.frame)
    canonical_summary = {
        "code_sha256": code_sha256,
        "config_sha256": config.raw_sha256,
        "dataset_identity": snapshot.identity,
        "dataset_sha256": snapshot.sha256,
        "engine_schema_version": _ENGINE_SCHEMA_VERSION,
        "event_study": event_study,
        "experiment_id": experiment_id,
        "strategy_family_id": config.strategy_family_id,
        "trial_id": config.trial_id,
    }
    result_artifact_id = sha256_bytes(canonical_bytes(canonical_summary))

    runtime_dir = _safe_runtime_dir(config.runtime_dir, engine_root)
    registry = ExperimentRegistry(
        runtime_dir / "experiments.sqlite3",
        engine_root / "migrations" / "001_experiment_registry.sql",
    )
    registry.initialize()
    durable = registry.record_or_reuse(
        experiment_id=experiment_id,
        trial_id=config.trial_id,
        strategy_family_id=config.strategy_family_id,
        dataset_path=str(snapshot.path),
        dataset_identity=snapshot.identity,
        dataset_sha256=snapshot.sha256,
        code_sha256=code_sha256,
        config_sha256=config.raw_sha256,
        started_at_ns=started_at_ns,
        finished_at_ns=time.time_ns(),
        result_artifact_id=result_artifact_id,
        canonical_summary=canonical_summary,
    )
    elapsed_ns = max(1, time.perf_counter_ns() - started_perf_ns)
    telemetry = _telemetry(snapshot.row_count, elapsed_ns)
    telemetry["sqlite_read_elapsed_ns"] = durable.sqlite_read_elapsed_ns
    telemetry["sqlite_write_elapsed_ns"] = durable.sqlite_write_elapsed_ns
    return RunOutcome(
        canonical_summary=durable.canonical_summary,
        result_artifact_id=durable.result_artifact_id,
        reused_registry_result=durable.reused,
        telemetry=telemetry,
    )


def _engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _code_sha256(engine_root: Path) -> str:
    source_paths = [
        path.relative_to(engine_root)
        for path in (engine_root / "research_engine").rglob("*.py")
    ]
    source_paths.extend(
        path.relative_to(engine_root)
        for path in (engine_root / "migrations").rglob("*.sql")
    )
    source_paths.extend([Path("pyproject.toml"), Path("requirements.txt")])
    return selected_tree_sha256(engine_root, source_paths)


def _load_dataset(config: EngineConfig) -> DatasetSnapshot:
    raw_path = config.dataset_path
    try:
        mode = raw_path.lstat().st_mode
    except FileNotFoundError as error:
        raise DatasetIntegrityError("dataset file is missing") from error
    if raw_path.is_symlink() or not raw_path.is_file():
        raise DatasetIntegrityError("dataset must be a regular non-symlink file")
    path = raw_path.resolve(strict=True)
    actual_sha256 = sha256_file(path)
    if actual_sha256 != config.dataset_sha256:
        raise DatasetIntegrityError("dataset SHA-256 does not match the explicit configuration")

    try:
        lazy_frame = pl.scan_parquet(str(path))
        schema = lazy_frame.collect_schema()
    except Exception as error:
        raise DatasetIntegrityError("dataset cannot be read as a valid Parquet input") from error
    schema_view = {name: str(schema[name]) for name in schema.names()}
    for column in _REQUIRED_COLUMNS:
        if column not in schema or schema[column] != pl.Int64:
            raise DatasetIntegrityError(f"dataset column {column!r} must be Int64")

    try:
        frame = lazy_frame.select(list(_REQUIRED_COLUMNS)).sort("open_time").collect()
    except Exception as error:
        raise DatasetIntegrityError("dataset lazy scan failed during materialization") from error
    if sha256_file(path) != actual_sha256:
        raise DatasetIntegrityError("dataset changed during the read-only scan")
    if frame.height == 0:
        raise DatasetIntegrityError("dataset must contain at least one row")
    if frame.null_count().row(0) != (0, 0, 0):
        raise DatasetIntegrityError("dataset required columns may not contain null values")
    timestamps = frame.get_column("open_time").to_list()
    if len(set(timestamps)) != len(timestamps):
        raise DatasetIntegrityError("dataset open_time values must be unique for deterministic ordering")

    metadata = {
        "byte_length": path.stat().st_size,
        "row_count": frame.height,
        "schema": schema_view,
        "sha256": actual_sha256,
    }
    return DatasetSnapshot(
        path=path,
        sha256=actual_sha256,
        identity=sha256_bytes(canonical_bytes(metadata)),
        row_count=frame.height,
        schema=schema_view,
        frame=frame,
    )


def _event_study(frame: pl.DataFrame) -> dict[str, int]:
    """Calculate a compact integer-only price-direction study in stable time order."""
    summary = frame.select(
        [
            pl.len().alias("row_count"),
            (pl.col("close") > pl.col("open")).cast(pl.Int64).sum().alias("up_count"),
            (pl.col("close") < pl.col("open")).cast(pl.Int64).sum().alias("down_count"),
            (pl.col("close") == pl.col("open")).cast(pl.Int64).sum().alias("flat_count"),
        ]
    ).row(0, named=True)
    up_count = int(summary["up_count"])
    down_count = int(summary["down_count"])
    return {
        "down_count": down_count,
        "flat_count": int(summary["flat_count"]),
        "net_direction": up_count - down_count,
        "row_count": int(summary["row_count"]),
        "up_count": up_count,
    }


def _safe_runtime_dir(runtime_dir: Path, engine_root: Path) -> Path:
    """Keep every A0 write inside its owned root, including runtime SQLite files."""
    owned_root = engine_root.resolve()
    raw_candidate = Path(os.path.abspath(str(runtime_dir)))
    try:
        raw_relative = raw_candidate.relative_to(owned_root)
    except ValueError as error:
        raise ConfigError("runtime_dir must remain inside research/engine") from error
    if not raw_relative.parts or raw_relative.parts[0] != "runtime":
        raise ConfigError("runtime_dir must remain under research/engine/runtime")
    current = owned_root
    for part in raw_relative.parts:
        current = current / part
        if current.is_symlink():
            raise ConfigError("runtime_dir must not contain symlinked components")
    candidate = raw_candidate.resolve(strict=False)
    try:
        candidate.relative_to((owned_root / "runtime").resolve(strict=False))
    except ValueError as error:
        raise ConfigError("runtime_dir must remain under research/engine/runtime") from error
    return candidate


def _telemetry(row_count: int, elapsed_ns: int) -> dict[str, Any]:
    """Observational performance data deliberately excluded from canonical identity."""
    telemetry: dict[str, Any] = {
        "elapsed_ns": elapsed_ns,
        "rows_per_second_integer": (row_count * 1_000_000_000) // elapsed_ns,
    }
    try:
        import resource

        telemetry["peak_memory_raw"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        telemetry["peak_memory_unit"] = (
            "bytes" if platform.system() == "Darwin" else "kilobytes"
        )
    except (ImportError, AttributeError):
        telemetry["peak_memory_reason"] = "resource.getrusage is unavailable on this platform"
    return telemetry
