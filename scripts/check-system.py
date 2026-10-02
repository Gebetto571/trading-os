#!/usr/bin/env python3
"""Read-only readiness checks. Configuration is data, never shell code."""

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from urllib.parse import unquote, urlsplit


UTC = dt.timezone.utc
ENVIRONMENT_KEYS = {"TRADING_OS_DB", "TRADING_OS_ACTOR", "TRADING_OS_DRIVE_ROOT_ID",
                    "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT",
                    "DATABASE_URL", "RUST_LOG"}


def read_private_text(path):
    """Reject special files before reading; never wait on a FIFO or follow a link."""
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0))
    try:
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_size > 1024 * 1024):
            raise ValueError("private metadata must be an owned regular file with mode 0600")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = None
            content = stream.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ValueError("private metadata too large")
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return content.decode("utf-8")


def read_private_json(path):
    record = json.loads(read_private_text(path))
    if not isinstance(record, dict):
        raise ValueError("private metadata must be an object")
    return record


def load_environment(path):
    """Read an owner-private, regular dotenv file without executing its contents."""
    content = read_private_text(path)
    values = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or key in values:
            raise ValueError("environment file contains an invalid or duplicate key")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1]:
                raise ValueError("environment file contains unsupported quoting")
            value = value[1:-1]
        elif re.search(r"[\s'\";|&<>`\\]", value):
            raise ValueError("environment file contains unsupported syntax")
        if "\x00" in value or "\n" in value or "\r" in value:
            raise ValueError("environment file contains invalid data")
        values[key] = value
    return values


def validate_runtime_environment(values):
    """Require one consistent local database target; never expose configuration."""
    message = "runtime database configuration invalid"
    required = ("POSTGRES_USER", "POSTGRES_DB", "POSTGRES_PASSWORD", "DATABASE_URL")
    if (not isinstance(values, dict) or not set(values).issubset(ENVIRONMENT_KEYS)
            or not all(isinstance(key, str) and isinstance(value, str)
                       for key, value in values.items())
            or not all(values.get(key) for key in required)
            or values.get("POSTGRES_PASSWORD") == "change-me"):
        raise ValueError(message)
    port = values.get("POSTGRES_PORT", "54329")
    if not re.fullmatch(r"[0-9]+", port) or not 0 < int(port) <= 65535:
        raise ValueError(message)
    uri = values["DATABASE_URL"]
    if re.search(r"[\x00-\x20\x7f]", uri) or re.search(r"%(?![a-fA-F0-9]{2})", uri):
        raise ValueError(message)
    try:
        parts = urlsplit(uri)
        valid = (parts.scheme in {"postgres", "postgresql"}
                 and parts.hostname in {"localhost", "127.0.0.1"}
                 and parts.port == int(port) and not parts.query and not parts.fragment
                 and parts.username is not None and parts.password is not None
                 and unquote(parts.username, errors="strict") == values["POSTGRES_USER"]
                 and unquote(parts.password, errors="strict") == values["POSTGRES_PASSWORD"]
                 and parts.path.startswith("/") and "/" not in parts.path[1:]
                 and unquote(parts.path[1:], errors="strict") == values["POSTGRES_DB"])
    except (ValueError, UnicodeError):
        raise ValueError(message) from None
    if not valid:
        raise ValueError(message)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return parsed.astimezone(UTC)


def age_seconds(value, now):
    age = (now - timestamp(value)).total_seconds()
    if age < -60:
        raise ValueError("timestamp is in the future")
    return max(0, int(age))


def evaluate_health(record, now, max_age):
    """A historical success never overrides the most recent failure or stale data."""
    if not isinstance(record, dict):
        raise ValueError("health record must be an object")
    observed_age = age_seconds(record.get("observed_at"), now)
    data_age = age_seconds(record.get("last_open_after"), now)
    healthy = (type(record.get("schema_version")) is int and record.get("schema_version") == 1
               and record.get("symbol") == "BTCUSDT"
               and record.get("status") in {"succeeded", "noop"}
               and record.get("database_reachable") is True
               and type(record.get("gaps_remaining")) is int and record.get("gaps_remaining") == 0
               and observed_age <= max_age and data_age <= max_age)
    return {"ok": healthy, "status": record.get("status"),
            "age_seconds": observed_age, "data_age_seconds": data_age,
            "last_data_open": record.get("last_open_after")}


def run(command, timeout=15, cwd=None):
    # Capture diagnostics: credentials and arbitrary tool errors never reach output.
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, cwd=cwd,
                          check=True).stdout.strip()


def inspect_deployment(runtime):
    def metadata(path):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022 or info.st_size > 1024 * 1024):
            raise ValueError("deployment metadata permissions invalid")
        record = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(record, dict):
            raise ValueError("deployment metadata must be an object")
        return record

    active = metadata(runtime / "active.json")
    relative = active.get("current", "")
    if active.get("schema_version") != 1 or not re.fullmatch(r"releases/[a-f0-9]{64}", relative):
        raise ValueError("deployment record invalid")
    release = runtime / relative
    binary = release / "market-data-import"
    manifest = metadata(release / "manifest.json")
    info = binary.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022
            or release.is_symlink() or (runtime / "releases").is_symlink()
            or not os.access(binary, os.X_OK)):
        raise ValueError("deployment binary unavailable")
    digest = hashlib.sha256()
    with binary.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    actual = digest.hexdigest()
    if (manifest.get("schema_version") != 1 or manifest.get("verdict") != "PASS"
            or manifest.get("sha256") != actual or relative != "releases/" + actual
            or not re.fullmatch(r"[a-f0-9]{40}", str(manifest.get("source_commit", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(manifest.get("source_tree_sha256", "")))):
        raise ValueError("deployment acceptance or hash mismatch")
    if "current_acceptance" in active:
        acceptance = active["current_acceptance"]
    else:
        # A legacy state carries the original acceptance, never a fabricated new one.
        acceptance = {"schema_version": 1, "release": relative,
                      "source_commit": manifest.get("source_commit"),
                      "source_tree_sha256": manifest.get("source_tree_sha256"),
                      "test_report_sha256": manifest.get("test_report_sha256"),
                      "accepted_at": manifest.get("created_at"), "origin": "legacy_manifest"}
    if (not isinstance(acceptance, dict) or type(acceptance.get("schema_version")) is not int
            or acceptance.get("schema_version") != 1
            or acceptance.get("release") != relative
            or acceptance.get("origin") not in {"activation", "legacy_manifest"}
            or not re.fullmatch(r"[a-f0-9]{40}", str(acceptance.get("source_commit", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(acceptance.get("source_tree_sha256", "")))
            or not re.fullmatch(r"[a-f0-9]{64}", str(acceptance.get("test_report_sha256", "")))):
        raise ValueError("deployment acceptance receipt invalid")
    timestamp(acceptance.get("accepted_at"))
    return {"binary_sha256": actual, "binary_source_commit": manifest["source_commit"],
            "accepted_source_commit": acceptance["source_commit"],
            "source_commit": acceptance["source_commit"],
            "accepted_source_tree_sha256": acceptance["source_tree_sha256"],
            "accepted_test_report_sha256": acceptance["test_report_sha256"],
            "accepted_at": acceptance["accepted_at"], "acceptance_origin": acceptance["origin"]}


def readiness(root, max_age=1800, health_directory=None):
    root = Path(root).resolve()
    now = dt.datetime.now(UTC)
    checks = []

    def add(name, ok, detail, **fields):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, **fields})

    values = {}
    try:
        values = load_environment(root / ".env")
        validate_runtime_environment(values)
        add("environment", True, "private local configuration accepted")
    except (OSError, ValueError, UnicodeError):
        add("environment", False, "configuration missing or not private regular data")

    architecture = platform.machine()
    add("architecture", platform.system() != "Darwin" or architecture == "arm64",
        architecture)
    try:
        version = run(["rustc", "--version"], cwd=root)
        add("rust", version.startswith("rustc 1.88.0 "), version.split(" (")[0])
    except (OSError, subprocess.SubprocessError):
        add("rust", False, "Rust 1.88.0 unavailable")
    python = root / "research/engine/.venv/bin/python"
    try:
        version = run([str(python), "-c", "import sys,polars,jsonschema; print('.'.join(map(str,sys.version_info[:3]))); print(polars.__version__); print(__import__('importlib.metadata',fromlist=['version']).version('jsonschema'))"], cwd=root)
        add("python", version.splitlines() == ["3.12.14", "1.35.2", "4.23.0"],
            "Python 3.12.14 and pinned test dependencies" if version.splitlines() == ["3.12.14", "1.35.2", "4.23.0"] else "Python or dependency version differs")
    except (OSError, subprocess.SubprocessError):
        add("python", False, "project Python or dependencies unavailable")

    data_end = None
    if values.get("POSTGRES_USER") and values.get("POSTGRES_DB"):
        sql = ("BEGIN READ ONLY; SET LOCAL statement_timeout='5000ms'; "
               "SELECT json_build_object('last_data_open',"
               "(SELECT max(open_time) FROM market_candles WHERE venue='binance' "
               "AND market_type='spot' AND symbol='BTCUSDT' AND interval='1m'),"
               "'last_successful_data_end',"
               "(SELECT range_end FROM market_data_sync_runs WHERE venue='binance' "
               "AND market_type='spot' AND symbol='BTCUSDT' AND interval='1m' "
               "AND status IN ('succeeded','noop') ORDER BY finished_at DESC LIMIT 1)); ROLLBACK;")
        try:
            output = run(["docker", "compose", "--env-file", str(root / ".env"), "-f",
                          str(root / "compose.market-data.yml"), "exec", "-T", "postgres",
                          "psql", "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-U",
                          values["POSTGRES_USER"], "-d", values["POSTGRES_DB"], "-c", sql], cwd=root)
            data = json.loads(output)
            age = age_seconds(data["last_data_open"], now)
            data_end = data.get("last_successful_data_end")
            add("database", True, "read-only query succeeded", **data)
            add("data_freshness", age <= max_age, "latest stored candle", age_seconds=age)
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            add("database", False, "read-only database query unavailable")
    else:
        add("database", False, "database configuration unavailable")

    runtime = Path(os.environ.get("TRADING_OS_RUNTIME_ROOT", str(Path.home() / "Library/Application Support/TradingOS/market-data")))
    try:
        deployment = inspect_deployment(runtime)
        add("deployment", True, "accepted immutable runtime binary", **deployment)
    except (OSError, ValueError, TypeError, KeyError):
        add("deployment", False, "accepted runtime binary missing or modified")
    health = Path(health_directory or os.environ.get("TRADING_OS_MARKET_DATA_HEALTH_DIR", str(runtime / "health")))
    try:
        if health.is_symlink():
            raise ValueError("health directory is a symbolic link")
        record = read_private_json(health / "latest.json")
        result = evaluate_health(record, now, max_age)
        ok = result.pop("ok")
        add("collector", ok, "latest attempt and candle freshness", **result)
    except (OSError, ValueError, TypeError):
        add("collector", False, "latest health record missing or invalid")

    return {"schema_version": 1, "observed_at": now.isoformat(),
            "verdict": "PASS" if all(item["ok"] for item in checks) else "FAIL",
            "last_successful_data_end": data_end, "checks": checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--health-directory", type=Path)
    parser.add_argument("--max-age-seconds", type=int, default=1800)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.max_age_seconds < 60:
        parser.error("max-age-seconds must be at least 60")
    result = readiness(args.repo_root, args.max_age_seconds, args.health_directory)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for item in result["checks"]:
            print(("OK" if item["ok"] else "FAIL") + " " + item["name"] + ": " + item["detail"])
        print("Last successful data end: " + str(result["last_successful_data_end"] or "unavailable"))
        print("Readiness: " + result["verdict"])
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
