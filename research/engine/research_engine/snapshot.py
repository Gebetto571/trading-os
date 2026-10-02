"""Read-only canonical Parquet snapshot evidence for research-only inputs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import polars as pl

from .errors import DatasetIntegrityError
from .hashing import canonical_bytes, sha256_bytes


_SNAPSHOT_SCHEMA_VERSION = "r0-canonical-parquet-snapshot-v1"
_MARKET_DATA_SCHEMA_VERSION = "1"
_YEAR_PATTERN = re.compile(r"year=(\d{4})\Z")
_MONTH_PATTERN = re.compile(r"month=(\d{2})\Z")
_PARTITION_FILE_NAME = "candles.parquet"

_STRING_COLUMNS = (
    "schema_version",
    "venue",
    "market_type",
    "symbol",
    "interval",
    "source",
    "source_file",
)
_SERIES_COLUMNS = ("venue", "market_type", "symbol", "interval")
_DECIMAL_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "base_asset_volume",
    "quote_asset_volume",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
)
_EXPECTED_SCHEMA = {
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
_EXPECTED_COLUMNS = tuple(_EXPECTED_SCHEMA)


@dataclass(frozen=True)
class CanonicalParquetSnapshot:
    """Immutable canonical evidence for one homogeneous interval partition tree."""

    _canonical_manifest_bytes: bytes
    snapshot_id: str

    @property
    def manifest(self) -> dict[str, Any]:
        """Return a defensive manifest copy without exposing snapshot state."""
        manifest = json.loads(self._canonical_manifest_bytes.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise DatasetIntegrityError("canonical snapshot manifest is not an object")
        return manifest

    def canonical_bytes(self) -> bytes:
        """Return the stable manifest bytes whose SHA-256 is ``snapshot_id``."""
        return self._canonical_manifest_bytes


@dataclass(frozen=True)
class CanonicalParquetMaterialization:
    """A defensive, descriptor-bound frame view of one canonical snapshot."""

    snapshot: CanonicalParquetSnapshot
    _frame: pl.DataFrame

    @property
    def frame(self) -> pl.DataFrame:
        """Return a clone so callers cannot mutate the retained frame view."""
        return self._frame.clone()


@dataclass(frozen=True)
class _FileSnapshot:
    device: int
    inode: int
    mode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def from_stat(cls, status: os.stat_result) -> "_FileSnapshot":
        return cls(
            device=status.st_dev,
            inode=status.st_ino,
            mode=status.st_mode,
            size=status.st_size,
            mtime_ns=status.st_mtime_ns,
            ctime_ns=status.st_ctime_ns,
        )


def build_canonical_snapshot(snapshot_root: Path) -> CanonicalParquetSnapshot:
    """Read and validate one canonical Parquet partition tree without writing it.

    ``snapshot_root`` must be a real local directory with the exact shape
    ``year=YYYY/month=MM/candles.parquet``.  The root therefore represents one
    homogeneous research series; callers must not mix intervals in one snapshot.
    """
    root = _validated_root(snapshot_root)
    partitions = _discover_partitions(root)
    entries = []
    series: Optional[dict[str, str]] = None
    previous_last_close_time_us: Optional[int] = None
    total_rows = 0
    first_open_time_us: Optional[int] = None
    last_open_time_us: Optional[int] = None

    for relative_path in partitions:
        evidence, partition_series = _read_partition(
            root,
            relative_path,
            previous_last_close_time_us,
        )
        if series is None:
            series = partition_series
        elif series != partition_series:
            raise DatasetIntegrityError("partition series identity differs from prior partition")
        entries.append(evidence)
        previous_last_close_time_us = evidence["last_close_time_us"]
        total_rows += evidence["row_count"]
        if first_open_time_us is None:
            first_open_time_us = evidence["first_open_time_us"]
        last_open_time_us = evidence["last_open_time_us"]

    if first_open_time_us is None or last_open_time_us is None or series is None:
        raise DatasetIntegrityError("canonical snapshot has no Parquet rows")

    manifest = {
        "market_data_schema_version": _MARKET_DATA_SCHEMA_VERSION,
        "partitions": entries,
        "row_count": total_rows,
        "schema": {name: str(dtype) for name, dtype in _EXPECTED_SCHEMA.items()},
        "series": series,
        "snapshot_schema_version": _SNAPSHOT_SCHEMA_VERSION,
        "first_open_time_us": first_open_time_us,
        "last_open_time_us": last_open_time_us,
    }
    manifest_bytes = canonical_bytes(manifest)
    return CanonicalParquetSnapshot(
        _canonical_manifest_bytes=manifest_bytes,
        snapshot_id=sha256_bytes(manifest_bytes),
    )


def materialize_canonical_snapshot(snapshot_root: Path) -> CanonicalParquetMaterialization:
    """Materialize one R0 snapshot without weakening its input integrity boundary.

    The snapshot is first built through the existing R0 inventory checks.  Every
    manifest-listed partition is then reopened through the same descriptor-bound
    path, rehashed before and after the scan, and matched back to the immutable
    manifest before its rows are accepted.
    """
    root = _validated_root(snapshot_root)
    snapshot = build_canonical_snapshot(root)
    manifest = snapshot.manifest
    raw_entries = manifest.get("partitions")
    raw_series = manifest.get("series")
    if not isinstance(raw_entries, list) or not isinstance(raw_series, dict):
        raise DatasetIntegrityError("canonical snapshot manifest shape is invalid")

    frames: list[pl.DataFrame] = []
    previous_last_close_time_us: Optional[int] = None
    for expected in raw_entries:
        if not isinstance(expected, dict) or not isinstance(expected.get("path"), str):
            raise DatasetIntegrityError("canonical snapshot partition manifest is invalid")
        relative_path = Path(expected["path"])
        evidence, series, frame = _scan_partition(
            root,
            relative_path,
            previous_last_close_time_us,
            materialize=True,
        )
        if evidence != expected or series != raw_series or frame is None:
            raise DatasetIntegrityError("canonical snapshot partition no longer matches manifest")
        previous_last_close_time_us = evidence["last_close_time_us"]
        frames.append(frame)

    if not frames:
        raise DatasetIntegrityError("canonical snapshot has no materializable partitions")
    frame = pl.concat(frames, how="vertical").sort("open_time")
    _validate_materialized_frame(frame, manifest)
    return CanonicalParquetMaterialization(snapshot=snapshot, _frame=frame)


def _validated_root(snapshot_root: Path) -> Path:
    raw_root = Path(snapshot_root).expanduser()
    if not raw_root.is_absolute() or any(part in {".", ".."} for part in raw_root.parts):
        raise DatasetIntegrityError("snapshot root must be an absolute canonical local path")
    try:
        root_mode = raw_root.lstat().st_mode
    except FileNotFoundError as error:
        raise DatasetIntegrityError("snapshot root is missing") from error
    if stat.S_ISLNK(root_mode) or not stat.S_ISDIR(root_mode):
        raise DatasetIntegrityError("snapshot root must be a non-symlink directory")
    return raw_root.resolve(strict=True)


def _discover_partitions(root: Path) -> tuple[Path, ...]:
    partitions = []
    year_paths = _plain_children(root, "snapshot root")
    if not year_paths:
        raise DatasetIntegrityError("snapshot root has no year partitions")
    for year_path in year_paths:
        _partition_number(year_path.name, _YEAR_PATTERN, "year")
        if not _is_plain_directory(year_path):
            raise DatasetIntegrityError(f"year partition is not a plain directory: {year_path.name}")
        month_paths = _plain_children(year_path, "year partition")
        if not month_paths:
            raise DatasetIntegrityError(f"year partition has no months: {year_path.name}")
        for month_path in month_paths:
            month = _partition_number(month_path.name, _MONTH_PATTERN, "month")
            if not 1 <= month <= 12 or not _is_plain_directory(month_path):
                raise DatasetIntegrityError(f"month partition is invalid: {month_path.name}")
            entries = _plain_children(month_path, "month partition")
            if len(entries) != 1 or entries[0].name != _PARTITION_FILE_NAME:
                raise DatasetIntegrityError(
                    f"month partition must contain exactly {_PARTITION_FILE_NAME}: {month_path}"
                )
            target = entries[0]
            if not _is_plain_regular_file(target):
                raise DatasetIntegrityError(f"partition is not a plain regular file: {target}")
            partitions.append(target.relative_to(root))
    return tuple(sorted(partitions, key=lambda path: path.as_posix()))


def _plain_children(path: Path, label: str) -> tuple[Path, ...]:
    try:
        children = tuple(sorted(path.iterdir(), key=lambda child: child.name))
    except OSError as error:
        raise DatasetIntegrityError(f"cannot inventory {label}") from error
    for child in children:
        try:
            if stat.S_ISLNK(child.lstat().st_mode):
                raise DatasetIntegrityError(f"symlink is not allowed in {label}: {child.name}")
        except OSError as error:
            raise DatasetIntegrityError(f"cannot inspect {label}: {child.name}") from error
    return children


def _partition_number(name: str, pattern: re.Pattern[str], label: str) -> int:
    match = pattern.fullmatch(name)
    if match is None:
        raise DatasetIntegrityError(f"invalid {label} partition name: {name}")
    value = int(match.group(1))
    if value == 0:
        raise DatasetIntegrityError(f"invalid {label} partition number: {name}")
    return value


def _is_plain_directory(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return not stat.S_ISLNK(mode) and stat.S_ISDIR(mode)


def _is_plain_regular_file(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    return not stat.S_ISLNK(mode) and stat.S_ISREG(mode)


def _read_partition(
    root: Path,
    relative_path: Path,
    previous_last_close_time_us: Optional[int],
) -> tuple[dict[str, Any], dict[str, str]]:
    evidence, series, _ = _scan_partition(
        root,
        relative_path,
        previous_last_close_time_us,
        materialize=False,
    )
    return evidence, series


def _scan_partition(
    root: Path,
    relative_path: Path,
    previous_last_close_time_us: Optional[int],
    *,
    materialize: bool,
) -> tuple[dict[str, Any], dict[str, str], Optional[pl.DataFrame]]:
    descriptor, before = _open_partition_descriptor(root, relative_path)
    try:
        first_sha256 = _hash_bound_descriptor(descriptor, before, relative_path)
        lazy_frame = pl.scan_parquet(_descriptor_parquet_path(descriptor))
        schema = lazy_frame.collect_schema()
        _validate_schema(schema, relative_path)
        null_counts = lazy_frame.select(
            [pl.col(name).null_count().alias(name) for name in _EXPECTED_COLUMNS]
        ).collect()
        timing = lazy_frame.select(
            [
                pl.col("schema_version"),
                *[pl.col(name) for name in _SERIES_COLUMNS],
                pl.col("open_time").cast(pl.Int64).alias("open_time_us"),
                pl.col("close_time").cast(pl.Int64).alias("close_time_us"),
            ]
        ).collect()
        frame = lazy_frame.collect() if materialize else None
    except Exception as error:
        raise DatasetIntegrityError(f"partition scan failed: {relative_path}") from error
    finally:
        os.close(descriptor)

    _assert_partition_path_unchanged(root, relative_path, before, first_sha256)

    if timing.height == 0:
        raise DatasetIntegrityError(f"partition has no rows: {relative_path}")
    null_row = null_counts.row(0, named=True)
    if any(int(value) != 0 for value in null_row.values()):
        raise DatasetIntegrityError(f"partition has null canonical values: {relative_path}")
    schema_versions = timing.get_column("schema_version").unique().to_list()
    if schema_versions != [_MARKET_DATA_SCHEMA_VERSION]:
        raise DatasetIntegrityError(f"partition schema_version is not {_MARKET_DATA_SCHEMA_VERSION}: {relative_path}")
    series = {
        name: _single_nonempty_string(timing.get_column(name).unique().to_list(), name, relative_path)
        for name in _SERIES_COLUMNS
    }

    open_times = [int(value) for value in timing.get_column("open_time_us").to_list()]
    close_times = [int(value) for value in timing.get_column("close_time_us").to_list()]
    previous_close_time_us: Optional[int] = None
    for open_time_us, close_time_us in zip(open_times, close_times):
        if close_time_us <= open_time_us:
            raise DatasetIntegrityError(f"partition close_time is not after open_time: {relative_path}")
        if previous_close_time_us is not None and open_time_us < previous_close_time_us:
            raise DatasetIntegrityError(f"partition timestamp ranges overlap or are unordered: {relative_path}")
        previous_close_time_us = close_time_us
    if (
        previous_last_close_time_us is not None
        and open_times[0] < previous_last_close_time_us
    ):
        raise DatasetIntegrityError(f"partition timestamp range overlaps prior partition: {relative_path}")

    return ({
        "byte_length": before.size,
        "first_close_time_us": close_times[0],
        "first_open_time_us": open_times[0],
        "last_close_time_us": close_times[-1],
        "last_open_time_us": open_times[-1],
        "path": relative_path.as_posix(),
        "row_count": timing.height,
        "sha256": first_sha256,
    }, series, frame)


def _validate_materialized_frame(frame: pl.DataFrame, manifest: dict[str, Any]) -> None:
    if frame.height != manifest.get("row_count"):
        raise DatasetIntegrityError("materialized row count differs from canonical manifest")
    if tuple(frame.columns) != _EXPECTED_COLUMNS:
        raise DatasetIntegrityError("materialized columns differ from canonical schema")
    for name, expected in _EXPECTED_SCHEMA.items():
        if frame.schema[name] != expected:
            raise DatasetIntegrityError(f"materialized column type differs: {name}")
    timestamps = [int(value) for value in frame.get_column("open_time").cast(pl.Int64).to_list()]
    if not timestamps or any(right <= left for left, right in zip(timestamps, timestamps[1:])):
        raise DatasetIntegrityError("materialized timestamps are not strictly ordered and unique")
    if (
        timestamps[0] != manifest.get("first_open_time_us")
        or timestamps[-1] != manifest.get("last_open_time_us")
    ):
        raise DatasetIntegrityError("materialized timestamp bounds differ from canonical manifest")


def _single_nonempty_string(values: list[Any], name: str, relative_path: Path) -> str:
    if len(values) != 1 or not isinstance(values[0], str) or not values[0]:
        raise DatasetIntegrityError(f"partition {name} is not one non-empty value: {relative_path}")
    return values[0]


def _validate_schema(schema: pl.Schema, relative_path: Path) -> None:
    if tuple(schema.names()) != _EXPECTED_COLUMNS:
        raise DatasetIntegrityError(f"partition schema columns differ: {relative_path}")
    for name, expected in _EXPECTED_SCHEMA.items():
        if schema[name] != expected:
            raise DatasetIntegrityError(f"partition schema type differs for {name}: {relative_path}")


def _open_partition_descriptor(root: Path, relative_path: Path) -> tuple[int, _FileSnapshot]:
    """Open one discovered partition through no-follow directory descriptors."""
    if len(relative_path.parts) != 3 or relative_path.parts[-1] != _PARTITION_FILE_NAME:
        raise DatasetIntegrityError(f"partition path is not canonical: {relative_path}")
    root_descriptor = _open_directory_descriptor(root, "snapshot root")
    directory_descriptors = [root_descriptor]
    try:
        for component in relative_path.parts[:-1]:
            next_descriptor = _open_directory_descriptor(
                component,
                f"partition path {relative_path}",
                dir_fd=directory_descriptors[-1],
            )
            directory_descriptors.append(next_descriptor)
        descriptor = _open_regular_descriptor(
            relative_path.parts[-1],
            relative_path,
            dir_fd=directory_descriptors[-1],
        )
        return descriptor, _FileSnapshot.from_stat(os.fstat(descriptor))
    except OSError as error:
        raise DatasetIntegrityError(f"partition cannot be safely opened: {relative_path}") from error
    finally:
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)


def _open_directory_descriptor(
    path: Union[Path, str],
    label: str,
    *,
    dir_fd: Optional[int] = None,
) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise DatasetIntegrityError("platform cannot open snapshot input without following symlinks")
    if not hasattr(os, "O_DIRECTORY"):
        raise DatasetIntegrityError("platform cannot bind snapshot directories without O_DIRECTORY")
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
            dir_fd=dir_fd,
        )
    except OSError as error:
        raise DatasetIntegrityError(f"cannot safely open {label}") from error
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise DatasetIntegrityError(f"{label} is not a directory")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_regular_descriptor(name: str, relative_path: Path, *, dir_fd: int) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise DatasetIntegrityError("platform cannot open snapshot input without following symlinks")
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as error:
        raise DatasetIntegrityError(f"partition cannot be safely opened: {relative_path}") from error
    try:
        before = _FileSnapshot.from_stat(os.fstat(descriptor))
        if not stat.S_ISREG(before.mode):
            raise DatasetIntegrityError(f"partition must be a regular file: {relative_path}")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _descriptor_parquet_path(descriptor: int) -> str:
    descriptor_root = Path("/dev/fd")
    if not descriptor_root.is_dir():
        raise DatasetIntegrityError("platform cannot bind Parquet reads to an open descriptor")
    return str(descriptor_root / str(descriptor))


def _hash_bound_descriptor(
    descriptor: int,
    expected: _FileSnapshot,
    relative_path: Path,
) -> str:
    before = _FileSnapshot.from_stat(os.fstat(descriptor))
    if before != expected or not stat.S_ISREG(before.mode):
        raise DatasetIntegrityError(f"partition changed before hashing: {relative_path}")
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        digest = hashlib.sha256()
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as error:
        raise DatasetIntegrityError(f"partition cannot be hashed through bound descriptor: {relative_path}") from error
    after = _FileSnapshot.from_stat(os.fstat(descriptor))
    if after != expected:
        raise DatasetIntegrityError(f"partition changed during hashing: {relative_path}")
    return digest.hexdigest()


def _assert_partition_path_unchanged(
    root: Path,
    relative_path: Path,
    expected: _FileSnapshot,
    expected_sha256: str,
) -> None:
    descriptor, current = _open_partition_descriptor(root, relative_path)
    try:
        current_sha256 = _hash_bound_descriptor(descriptor, current, relative_path)
    finally:
        os.close(descriptor)
    if current != expected or current_sha256 != expected_sha256:
        raise DatasetIntegrityError(f"partition path changed during read: {relative_path}")
