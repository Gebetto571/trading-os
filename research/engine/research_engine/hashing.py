"""Canonical hashes for A0 inputs, source, configuration, and results."""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any, Iterable

from .errors import DatasetIntegrityError


def canonical_bytes(value: Any) -> bytes:
    """Encode only deterministic JSON primitives in a stable form."""
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    """Hash a regular, non-symlink file without ever writing it."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise DatasetIntegrityError("dataset file is missing") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise DatasetIntegrityError("dataset must be a regular non-symlink file")

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def required_regular_file(path: Path, label: str) -> Path:
    """Reject missing, symlinked, or non-regular inputs before processing."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise DatasetIntegrityError(f"{label} is missing") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise DatasetIntegrityError(f"{label} must be a regular non-symlink file")
    return path.resolve(strict=True)


def selected_tree_sha256(root: Path, relative_paths: Iterable[Path]) -> str:
    """Hash a sorted manifest so source identity is independent of file-system order."""
    entries = []
    for relative_path in sorted(relative_paths, key=lambda item: item.as_posix()):
        absolute_path = root / relative_path
        if not absolute_path.is_file() or absolute_path.is_symlink():
            raise DatasetIntegrityError(
                f"required source identity input is not a regular file: {relative_path}"
            )
        entries.append(
            {
                "path": relative_path.as_posix(),
                "sha256": sha256_file(absolute_path),
            }
        )
    return sha256_bytes(canonical_bytes(entries))
