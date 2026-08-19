"""A deliberately small, fail-closed TOML subset for A0."""

from __future__ import annotations

import hashlib
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError


_REQUIRED_KEYS = frozenset(
    {
        "dataset_path",
        "dataset_sha256",
        "runtime_dir",
        "trial_id",
        "strategy_family_id",
    }
)
_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EngineConfig:
    """All configuration values that influence an A0 experiment identity."""

    path: Path
    raw_sha256: str
    dataset_path: Path
    dataset_sha256: str
    runtime_dir: Path
    trial_id: str
    strategy_family_id: str


def _read_regular_config(path: Path) -> bytes:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise ConfigError("configuration file is missing") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise ConfigError("configuration file must be a regular non-symlink file")
    return path.read_bytes()


def _parse_string(value: str, line_number: int) -> str:
    if len(value) < 2 or value[0] != '"' or value[-1] != '"':
        raise ConfigError(f"line {line_number}: values must be quoted strings")
    inner = value[1:-1]
    if "\\" in inner or "\n" in inner or "\r" in inner:
        raise ConfigError(f"line {line_number}: escapes and multiline values are forbidden")
    return inner


def _parse_flat_toml(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigError("configuration must be UTF-8") from error

    parsed: dict[str, str] = {}
    for line_number, source_line in enumerate(text.splitlines(), start=1):
        line = source_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line or line.count("=") != 1:
            raise ConfigError(f"line {line_number}: expected one key/value assignment")
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not _KEY_PATTERN.fullmatch(key) or key not in _REQUIRED_KEYS:
            raise ConfigError(f"line {line_number}: unsupported configuration key")
        if key in parsed:
            raise ConfigError(f"line {line_number}: duplicate configuration key")
        parsed[key] = _parse_string(raw_value, line_number)

    if set(parsed) != _REQUIRED_KEYS:
        missing = sorted(_REQUIRED_KEYS.difference(parsed))
        unexpected = sorted(set(parsed).difference(_REQUIRED_KEYS))
        raise ConfigError(f"configuration key mismatch; missing={missing}; unexpected={unexpected}")
    return parsed


def _resolve_local_path(config_path: Path, raw_value: str, label: str) -> Path:
    if not raw_value or raw_value.startswith(("http:", "https:", "drive:")):
        raise ConfigError(f"{label} must be a non-empty local path")
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return candidate
    return config_path.parent / candidate


def load_config(path: Path) -> EngineConfig:
    """Load precisely the local values A0 allows, with no ambient configuration."""
    raw = _read_regular_config(path)
    values = _parse_flat_toml(raw)
    if not _HASH_PATTERN.fullmatch(values["dataset_sha256"]):
        raise ConfigError("dataset_sha256 must be a lower-case SHA-256 value")
    if not values["trial_id"] or not values["strategy_family_id"]:
        raise ConfigError("trial_id and strategy_family_id must be non-empty")

    resolved_path = path.resolve(strict=True)
    return EngineConfig(
        path=resolved_path,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        dataset_path=_resolve_local_path(resolved_path, values["dataset_path"], "dataset_path"),
        dataset_sha256=values["dataset_sha256"],
        runtime_dir=_resolve_local_path(resolved_path, values["runtime_dir"], "runtime_dir"),
        trial_id=values["trial_id"],
        strategy_family_id=values["strategy_family_id"],
    )
