#!/bin/bash
# Shared machine setup helpers. Dotenv is data; it is never sourced as shell code.

tos_init() {
    TOS_REPOSITORY_ROOT="$(cd -- "$1" && pwd -P)" || return 1
    TOS_ENV_FILE="${TOS_REPOSITORY_ROOT}/.env"
    TOS_RUNTIME_ROOT="${TRADING_OS_RUNTIME_ROOT:-${HOME}/Library/Application Support/TradingOS/market-data}"
    TOS_HEALTH_DIRECTORY="${TRADING_OS_MARKET_DATA_HEALTH_DIR:-${TOS_RUNTIME_ROOT}/health}"
    TOS_PYTHON="${TRADING_OS_PYTHON:-${TOS_REPOSITORY_ROOT}/research/engine/.venv/bin/python}"
    if [[ ! -x "${TOS_PYTHON}" && -z "${TRADING_OS_PYTHON:-}" ]]; then
        TOS_PYTHON="${HOME}/.local/bin/python3.12"
        if [[ ! -x "${TOS_PYTHON}" ]]; then
            TOS_PYTHON="$(command -v python3 || true)"
        fi
    fi
}

tos_python() { printf '%s\n' "${TOS_PYTHON}"; }

tos_python_action() {
    [[ -x "${TOS_PYTHON:-}" ]] || { printf '%s\n' 'project Python unavailable' >&2; return 69; }
    PYTHONDONTWRITEBYTECODE=1 "${TOS_PYTHON}" - \
        "${TOS_REPOSITORY_ROOT}" "${TOS_RUNTIME_ROOT}" "${TOS_HEALTH_DIRECTORY}" "$@" <<'PY'
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import runpy
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
root, runtime, health = map(Path, sys.argv[1:4])
action, *args = sys.argv[4:]
RUNTIME_KEYS = {
    "TRADING_OS_DB", "TRADING_OS_ACTOR", "TRADING_OS_DRIVE_ROOT_ID",
    "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "POSTGRES_PORT",
    "DATABASE_URL", "RUST_LOG",
}


def run(command):
    return subprocess.check_output(command, cwd=root, stderr=subprocess.DEVNULL, text=True).strip()


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("directory is a symbolic link")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("directory ownership invalid")
    os.chmod(path, 0o700)


def runtime_directory():
    if not runtime.is_absolute() or runtime.resolve() == root or root in runtime.resolve().parents:
        raise ValueError("runtime must be outside the repository")
    private_dir(runtime)


def regular_owned(path, executable=False):
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError("file must be regular, owned and not writable by others")
    if executable and not info.st_mode & stat.S_IXUSR:
        raise ValueError("file is not executable")
    return info


def read_json(path):
    if regular_owned(path).st_size > 1024 * 1024:
        raise ValueError("metadata too large")
    result = json.loads(Path(path).read_text())
    if not isinstance(result, dict):
        raise ValueError("metadata must be an object")
    return result


def atomic_bytes(path, content, mode=0o600):
    path = Path(path)
    private_dir(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_json(path, content):
    atomic_bytes(path, (json.dumps(content, sort_keys=True, indent=2) + "\n").encode())


def source_hash():
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, stderr=subprocess.DEVNULL
    ).split(b"\0")
    result = hashlib.sha256()
    for raw in sorted(set(item for item in paths if item)):
        path = root / os.fsdecode(raw)
        result.update(raw + b"\0")
        if not path.exists() and not path.is_symlink():
            result.update(b"deleted\0")
        elif path.is_symlink():
            result.update(b"120000\0" + os.fsencode(os.readlink(path)) + b"\0")
        elif path.is_file():
            mode = b"100755" if path.stat().st_mode & 0o111 else b"100644"
            result.update(mode + b"\0" + digest(path).encode() + b"\0")
        else:
            raise ValueError("unsupported source tree entry")
    return result.hexdigest()


def environment(path):
    parser = runpy.run_path(str(root / "scripts/check-system.py"), run_name="trading_os_checks")
    values = parser["load_environment"](Path(path))
    if not set(values).issubset(RUNTIME_KEYS):
        raise ValueError("environment contains an unsupported key")
    return values


def verify_native(path):
    # A candidate must be a native executable for this host, never a shell script.
    details = run(["/usr/bin/file", "-b", str(path)])
    machine = platform.machine()
    if platform.system() == "Darwin":
        if "Mach-O" not in details or machine not in details:
            raise ValueError("candidate architecture differs")
    elif platform.system() == "Linux":
        expected = {"x86_64": "x86-64", "aarch64": "aarch64"}.get(machine, machine)
        if "ELF" not in details or expected not in details:
            raise ValueError("candidate architecture differs")
    else:
        raise ValueError("unsupported executable platform")


def validate_release(relative):
    if not isinstance(relative, str) or not re.fullmatch(r"releases/[0-9a-f]{64}", relative):
        raise ValueError("invalid release reference")
    folder = runtime / relative
    if folder.is_symlink() or (runtime / "releases").is_symlink():
        raise ValueError("release directory is a symbolic link")
    binary = folder / "market-data-import"
    regular_owned(binary, executable=True)
    manifest = read_json(folder / "manifest.json")
    actual = digest(binary)
    if (manifest.get("schema_version") != 1 or manifest.get("verdict") != "PASS"
            or manifest.get("sha256") != actual or folder.name != actual
            or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_commit", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("source_tree_sha256", "")))):
        raise ValueError("release verification failed")
    return binary


def active_state():
    if (not runtime.is_absolute() or runtime.is_symlink() or runtime.resolve() == root
            or root in runtime.resolve().parents):
        raise ValueError("runtime must be outside the repository")
    state = read_json(runtime / "active.json")
    if state.get("schema_version") != 1:
        raise ValueError("invalid active release state")
    validate_release(state.get("current"))
    return state


def activate(report_path):
    runtime_directory()
    candidate = read_json(root / "target/deploy-market-data/candidate.json")
    report = read_json(report_path)
    commit, tree = run(["git", "rev-parse", "HEAD"]), source_hash()
    if (report.get("schema_version") != 1 or report.get("verdict") != "PASS"
            or report.get("isolated_database") is not True
            or report.get("container_cleanup_verified") is not True
            or report.get("bridge_research_tests_status") != "PASS"
            or report.get("rust_tests_status") != "PASS"
            or report.get("python_version") != "3.12.14"
            or not str(report.get("rust_version", "")).startswith("rustc 1.88.0 ")
            or report.get("source_commit") != commit or candidate.get("source_commit") != commit
            or report.get("source_tree_sha256") != tree or candidate.get("source_tree_sha256") != tree):
        raise ValueError("build and passing tests must match the current source tree")
    binary = root / "target/release/market-data-import"
    regular_owned(binary, executable=True)
    actual = digest(binary)
    if candidate.get("sha256") != actual:
        raise ValueError("candidate changed after build")
    verify_native(binary)
    relative = "releases/" + actual
    releases = runtime / "releases"
    private_dir(releases)
    folder = runtime / relative
    if not folder.exists():
        staging = Path(tempfile.mkdtemp(prefix=".candidate-", dir=releases))
        try:
            shutil.copyfile(binary, staging / "market-data-import")
            os.chmod(staging / "market-data-import", 0o500)
            manifest = {
                "schema_version": 1, "verdict": "PASS", "sha256": actual,
                "source_commit": commit, "source_tree_sha256": tree,
                "test_report_sha256": digest(report_path),
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            atomic_json(staging / "manifest.json", manifest)
            if digest(staging / "market-data-import") != actual:
                raise ValueError("candidate copy verification failed")
            os.replace(staging, folder)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    validate_release(relative)
    old = active_state() if (runtime / "active.json").exists() else {}
    if old.get("current") == relative:
        print("Already active; previous release preserved.")
        return
    # Both pointers change in a single atomic replacement. In-flight runs keep
    # their already resolved immutable executable.
    atomic_json(runtime / "active.json", {
        "schema_version": 1, "current": relative, "previous": old.get("current"),
    })
    print("Verified release activated.")


def configure():
    env = root / ".env"
    if env.exists() or env.is_symlink():
        environment(env)
        created = False
    else:
        template = (root / ".env.example").read_bytes()
        descriptor = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(template)
            stream.flush()
            os.fsync(stream.fileno())
        created = True
    runtime_directory()
    private_dir(health)
    private_dir(runtime / "logs")
    template = plistlib.loads((root / "ops/launchd/com.tradingos.market-data.btcusdt-sync.plist").read_bytes())
    template["ProgramArguments"] = ["/bin/bash", str(root / "scripts/sync-btcusdt.sh")]
    template["WorkingDirectory"] = str(root)
    template["StandardOutPath"] = str(runtime / "logs/sync.log")
    template["StandardErrorPath"] = str(runtime / "logs/sync.log")
    template["EnvironmentVariables"] = {
        "PATH": str(Path.home() / ".cargo/bin") + ":/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "TRADING_OS_PYTHON": str(root / "research/engine/.venv/bin/python"),
        "TRADING_OS_RUNTIME_ROOT": str(runtime),
        "TRADING_OS_MARKET_DATA_HEALTH_DIR": str(health),
    }
    destination = Path.home() / "Library/LaunchAgents/com.tradingos.market-data.btcusdt-sync.plist"
    if destination.is_symlink():
        raise ValueError("agent configuration is a symbolic link")
    atomic_bytes(destination, plistlib.dumps(template))
    print("Existing .env preserved." if not created else "Private .env created; replace example credentials before activation.")
    print("User LaunchAgent configuration prepared; no service started.")


try:
    if action == "env":
        for key, value in environment(args[0] if args else root / ".env").items():
            print("export " + key + "=" + shlex.quote(value))
    elif action == "source-hash":
        print(source_hash())
    elif action == "release-path":
        state = active_state()
        print(validate_release(state.get(args[0] if args else "current")))
    elif action == "candidate":
        if len(args) != 2 or source_hash() != args[0] or run(["git", "rev-parse", "HEAD"]) != args[1]:
            raise ValueError("source changed after compilation")
        binary = root / "target/release/market-data-import"
        regular_owned(binary, executable=True)
        verify_native(binary)
        atomic_json(root / "target/deploy-market-data/candidate.json", {
            "schema_version": 1, "source_commit": args[1],
            "source_tree_sha256": args[0], "sha256": digest(binary),
        })
        print("Candidate built and hashed; active release unchanged.")
    elif action == "activate":
        activate(Path(args[0]))
    elif action == "rollback":
        # A broken current executable must not prevent returning to a good one.
        state = read_json(runtime / "active.json")
        if state.get("schema_version") != 1:
            raise ValueError("invalid active release state")
        validate_release(state.get("previous"))
        atomic_json(runtime / "active.json", {
            "schema_version": 1, "current": state["previous"], "previous": state["current"],
        })
        print("Previous verified release restored.")
    elif action == "configure":
        configure()
    elif action == "validate-env":
        values = environment(root / ".env")
        checks = runpy.run_path(str(root / "scripts/check-system.py"), run_name="trading_os_checks")
        checks["validate_runtime_environment"](values)
    elif action == "validate-health":
        record = read_json(health / "latest.json")
        observed = dt.datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
        now = dt.datetime.now(dt.timezone.utc).timestamp()
        if (observed.tzinfo is None or not int(args[0]) <= observed.timestamp() <= now + 60
                or record.get("schema_version") != 1 or record.get("symbol") != "BTCUSDT"
                or record.get("status") not in {"succeeded", "noop", "skipped"}):
            raise ValueError("collector did not publish a current health record")
    else:
        raise ValueError("unknown operation")
except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
    # Deliberately never print raw exceptions, config content or subprocess errors.
    print("Market-data operation failed (" + action + "); configuration or verified evidence is unavailable.", file=sys.stderr)
    sys.exit(1)
PY
}

tos_load_env() {
    local assignments
    assignments="$(tos_python_action env "${1:-${TOS_ENV_FILE}}")" || return 1
    # Only allowlisted identifiers and Python shlex.quote data reach eval.
    eval "${assignments}"
}

tos_source_tree_sha256() { tos_python_action source-hash; }
tos_release_path() { tos_python_action release-path "${1:-current}"; }

tos_health_failure() {
    # Pure shell fallback remains available when Python, config or binary is absent.
    local code="${1:-boot_failed}" stamp record temporary
    case "${code}" in *[!a-z_]*|'') code=boot_failed ;; esac
    stamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    record="{\"schema_version\":1,\"observed_at\":\"${stamp}\",\"status\":\"failed\",\"database_reachable\":false,\"symbol\":\"BTCUSDT\",\"rows_fetched\":0,\"rows_inserted\":0,\"rows_repaired\":0,\"gaps_remaining\":0,\"partitions_verified\":0,\"duration_ms\":0,\"error\":\"${code}\"}"
    umask 077
    if [[ ! -L "${TOS_HEALTH_DIRECTORY}" ]] &&
        mkdir -p "${TOS_HEALTH_DIRECTORY}" &&
        chmod 700 "${TOS_HEALTH_DIRECTORY}" &&
        [[ ! -d "${TOS_HEALTH_DIRECTORY}/latest.json" ]]; then
        temporary="$(mktemp "${TOS_HEALTH_DIRECTORY}/.latest.json.XXXXXX")" || return 1
        printf '%s\n' "${record}" >"${temporary}"
        chmod 600 "${temporary}"
        mv -f "${temporary}" "${TOS_HEALTH_DIRECTORY}/latest.json"
        # A malformed history entry must not block the current failure signal.
        if [[ ! -L "${TOS_HEALTH_DIRECTORY}/history.jsonl" ]] &&
            { [[ ! -e "${TOS_HEALTH_DIRECTORY}/history.jsonl" ]] ||
              [[ -f "${TOS_HEALTH_DIRECTORY}/history.jsonl" ]]; }; then
            printf '%s\n' "${record}" >>"${TOS_HEALTH_DIRECTORY}/history.jsonl"
            chmod 600 "${TOS_HEALTH_DIRECTORY}/history.jsonl"
        fi
    fi
    printf '%s\n' "${record}"
}
