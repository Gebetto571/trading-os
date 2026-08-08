"""State-preserving retention dry-run primitives.

The function below plans quarantine and rollback metadata only.  It never deletes,
moves, opens, or mutates a candidate path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath


class RetentionPlanError(ValueError):
    """Raised when a dry-run plan would be ambiguous or unsafe."""


@dataclass(frozen=True)
class QuarantinePlan:
    candidates: tuple[str, ...]
    protected_paths: tuple[str, ...]
    rollback_manifest_sha256: str


def plan_quarantine_dry_run(
    candidates: Iterable[str], protected_paths: Iterable[str] = (),
) -> QuarantinePlan:
    """Return a deterministic non-mutating plan and rollback-manifest identity."""

    normalized_candidates = _normalize_paths(candidates)
    normalized_protected = _normalize_paths(protected_paths)
    if set(normalized_candidates) & set(normalized_protected):
        raise RetentionPlanError("korunan yol quarantine adayına eklenemez")

    manifest = json.dumps(
        {"candidates": normalized_candidates, "protected_paths": normalized_protected},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return QuarantinePlan(
        candidates=tuple(normalized_candidates),
        protected_paths=tuple(normalized_protected),
        rollback_manifest_sha256=hashlib.sha256(manifest).hexdigest(),
    )


def _normalize_paths(paths: Iterable[str]) -> list[str]:
    values: list[str] = []
    for raw in paths:
        if not isinstance(raw, str) or not raw.strip():
            raise RetentionPlanError("yol boş olamaz")
        path = PurePosixPath(raw.replace("\\", "/"))
        if path.is_absolute() or "." in path.parts or ".." in path.parts:
            raise RetentionPlanError("yol repository göreli ve normalize olmalı")
        value = path.as_posix()
        if value in values:
            raise RetentionPlanError("aynı yol iki kez planlanamaz")
        values.append(value)
    return sorted(values)
