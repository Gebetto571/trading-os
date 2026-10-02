"""Fail-closed retention dry-run primitives.

This module only inspects candidate files to bind a deterministic retention
plan. It never quarantines, moves, deletes, or otherwise mutates them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Union


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RetentionPlanError(ValueError):
    """Raised when a dry-run plan would be ambiguous or unsafe."""


@dataclass(frozen=True)
class QuarantinePlan:
    candidates: tuple[str, ...]
    protected_paths: tuple[str, ...]
    candidate_sha256: tuple[tuple[str, str], ...]
    rollback_manifest_sha256: str


def plan_quarantine_dry_run(
    candidates: Iterable[str],
    protected_paths: Iterable[str] = (),
    *,
    repository_root: Union[Path, str],
    expected_sha256: Mapping[str, str],
) -> QuarantinePlan:
    """Return a hash-bound, deterministic plan without changing any file.

    ``protected_paths`` remains the caller-supplied canonical protection source;
    this function does not maintain a second copy of that list.
    Any separately authorized physical executor must repeat this validation
    immediately before acting; a dry-run plan is evidence, never execution authority.
    """

    root = _verified_repository_root(repository_root)
    normalized_candidates = _normalize_paths(candidates, "quarantine adayları")
    normalized_protected = _normalize_paths(protected_paths, "korunan yollar")
    _reject_protected_relations(normalized_candidates, normalized_protected)
    normalized_hashes = _normalize_expected_hashes(expected_sha256, normalized_candidates)
    tracked_paths = _tracked_paths(root)

    for candidate in normalized_candidates:
        _validate_candidate(root, candidate, normalized_hashes[candidate], tracked_paths)

    manifest = json.dumps(
        {
            "candidate_sha256": normalized_hashes,
            "candidates": normalized_candidates,
            "protected_paths": normalized_protected,
            "repository_root": str(root),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return QuarantinePlan(
        candidates=tuple(normalized_candidates),
        protected_paths=tuple(normalized_protected),
        candidate_sha256=tuple(sorted(normalized_hashes.items())),
        rollback_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
    )

def _verified_repository_root(repository_root: Union[Path, str]) -> Path:
    if not isinstance(repository_root, (str, Path)):
        raise RetentionPlanError("repository root geçerli bir yol olmalı")
    raw_root = Path(repository_root)
    if not raw_root.is_absolute() or raw_root.is_symlink():
        raise RetentionPlanError("repository root mutlak ve symlink olmayan yol olmalı")
    try:
        root = raw_root.resolve(strict=True)
    except OSError as error:
        raise RetentionPlanError("repository root çözümlenemedi") from error
    if not root.is_dir():
        raise RetentionPlanError("repository root dizin olmalı")
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=False,
            capture_output=True,
            text=True,
        )
        git_root = Path(result.stdout.strip()).resolve(strict=True)
    except (OSError, ValueError) as error:
        raise RetentionPlanError("Git repository root doğrulanamadı") from error
    if result.returncode != 0 or git_root != root:
        raise RetentionPlanError("repository root Git çalışma ağacı kökü olmalı")
    return root


def _normalize_paths(paths: Iterable[str], field: str) -> list[str]:
    if isinstance(paths, (str, bytes)):
        raise RetentionPlanError(f"{field} liste olmalı")
    try:
        iterator = iter(paths)
    except TypeError as error:
        raise RetentionPlanError(f"{field} liste olmalı") from error
    values: list[str] = []
    for raw in iterator:
        value = _normalize_path(raw, field)
        if value in values:
            raise RetentionPlanError("aynı yol iki kez planlanamaz")
        values.append(value)
    return sorted(values)


def _normalize_path(raw: object, field: str) -> str:
    if not isinstance(raw, str) or not raw or raw != raw.strip():
        raise RetentionPlanError(f"{field} içindeki yol boş veya belirsiz")
    if "\\" in raw or (len(raw) >= 2 and raw[0].isalpha() and raw[1] == ":"):
        raise RetentionPlanError("yol yalnız canonical repository-relative POSIX biçiminde olmalı")
    path = PurePosixPath(raw)
    value = path.as_posix()
    if (
        path.is_absolute()
        or value in {"", "."}
        or "." in path.parts
        or ".." in path.parts
        or ".git" in path.parts
        or raw != value
    ):
        raise RetentionPlanError("yol repository göreli ve normalize olmalı")
    return value


def _reject_protected_relations(candidates: list[str], protected_paths: list[str]) -> None:
    for candidate in candidates:
        for protected_path in protected_paths:
            if _same_or_descendant(candidate, protected_path) or _same_or_descendant(
                protected_path, candidate
            ):
                raise RetentionPlanError("korunan yol veya ilişkili dizini quarantine adayına eklenemez")


def _same_or_descendant(path: str, possible_ancestor: str) -> bool:
    return path == possible_ancestor or path.startswith(f"{possible_ancestor}/")


def _normalize_expected_hashes(
    expected_sha256: Mapping[str, str], candidates: list[str]
) -> dict[str, str]:
    if not isinstance(expected_sha256, Mapping):
        raise RetentionPlanError("aday SHA-256 kanıtı eşleme olmalı")
    normalized: dict[str, str] = {}
    for raw_path, digest in expected_sha256.items():
        path = _normalize_path(raw_path, "aday SHA-256 kanıtı")
        if path in normalized or not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
            raise RetentionPlanError("aday SHA-256 kanıtı geçersiz")
        normalized[path] = digest
    if set(normalized) != set(candidates):
        raise RetentionPlanError("her aday için yalnız bir SHA-256 kanıtı gerekli")
    return {candidate: normalized[candidate] for candidate in candidates}


def _tracked_paths(root: Path) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise RetentionPlanError("Git tracked-path envanteri okunamadı") from error
    if result.returncode != 0:
        raise RetentionPlanError("Git tracked-path envanteri doğrulanamadı")
    return {
        entry.decode("utf-8", errors="strict")
        for entry in result.stdout.split(b"\0")
        if entry
    }


def _validate_candidate(root: Path, candidate: str, expected_digest: str, tracked_paths: set[str]) -> None:
    if candidate in tracked_paths:
        raise RetentionPlanError("Git-tracked dosya quarantine adayı olamaz")
    actual_digest = _sha256_regular_file_at(root, candidate)
    if actual_digest != expected_digest:
        raise RetentionPlanError("aday SHA-256 kanıtı güncel içerikle eşleşmiyor")


def _sha256_regular_file_at(root: Path, candidate: str) -> str:
    required_flags = ("O_NOFOLLOW", "O_DIRECTORY")
    if any(not hasattr(os, name) for name in required_flags):
        raise RetentionPlanError("platform symlink-güvenli dry-run doğrulamasını desteklemiyor")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    file_flags = os.O_RDONLY | os.O_NOFOLLOW
    directory_fds: list[int] = []
    file_descriptor = None
    try:
        directory_fds.append(os.open(str(root), directory_flags))
        for component in PurePosixPath(candidate).parts[:-1]:
            next_directory = os.open(component, directory_flags, dir_fd=directory_fds[-1])
            directory_fds.append(next_directory)
            _reject_nested_git_repository(next_directory)
        file_descriptor = os.open(
            PurePosixPath(candidate).name,
            file_flags,
            dir_fd=directory_fds[-1],
        )
        before = os.fstat(file_descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RetentionPlanError("aday regular dosya olmalı")
        digest = hashlib.sha256()
        while True:
            block = os.read(file_descriptor, 64 * 1024)
            if not block:
                break
            digest.update(block)
        after = os.fstat(file_descriptor)
        if not _same_file_snapshot(before, after):
            raise RetentionPlanError("aday hash doğrulaması sırasında değişti")
        return digest.hexdigest()
    except RetentionPlanError:
        raise
    except OSError as error:
        raise RetentionPlanError("aday repository içinde symlink olmayan regular dosya olmalı") from error
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        for directory_descriptor in reversed(directory_fds):
            os.close(directory_descriptor)


def _reject_nested_git_repository(directory_descriptor: int) -> None:
    try:
        os.stat(".git", dir_fd=directory_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        raise RetentionPlanError("aday dizininin Git sınırı doğrulanamadı") from error
    raise RetentionPlanError("iç içe Git çalışma ağacındaki aday reddedildi")


def _same_file_snapshot(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) == (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    )
