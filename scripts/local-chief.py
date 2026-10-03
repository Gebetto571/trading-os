#!/usr/bin/env python3
"""Run one locally reviewed health task; incoming prose is never executable."""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import io
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trading_os_bridge import cli
from trading_os_bridge.local_acceptance import accept_task, validate_task
from trading_os_bridge.store import Store
from trading_os_bridge.validation import canonical_bytes, parse_json_strict, sha256_bytes

CHECK_NAMES = {"environment", "architecture", "rust", "python", "database",
               "data_freshness", "deployment", "collector"}
TIMEOUT_SECONDS = 60


class WorkerError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise WorkerError("invalid_arguments")


def child_environment():
    # Incoming task data and ambient GIT_* overrides never configure a subprocess.
    home = Path.home()
    return {"HOME": str(home), "LANG": "C", "LC_ALL": "C", "PYTHONDONTWRITEBYTECODE": "1",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "PATH": ":".join(map(str, [home / ".cargo/bin", home / ".local/bin",
                       Path("/opt/homebrew/bin"), Path("/Applications/Docker.app/Contents/Resources/bin"),
                       Path("/usr/bin"), Path("/bin"), Path("/usr/sbin"), Path("/sbin")]))}


def snapshot(repo):
    def git(*arguments):
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *arguments],
            cwd=repo, env=child_environment(), stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=15, check=False, shell=False,
        )
        if result.returncode:
            raise WorkerError("checkout_verification_failed")
        return result.stdout
    head = git("rev-parse", "HEAD").decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise WorkerError("checkout_verification_failed")
    return {"head": head,
            "diff_sha256": sha256_bytes(git("diff", "--no-ext-diff", "--no-textconv", "--binary", "HEAD", "--")),
            "status_sha256": sha256_bytes(git("status", "--porcelain=v1", "--untracked-files=all", "-z"))}


def selected_paths(args):
    repo = Path(args.repo)
    if not repo.is_absolute() or repo.resolve(strict=True) != ROOT.resolve(strict=True):
        raise WorkerError("wrong_repository")
    repo = repo.resolve(strict=True)
    paths = {}
    for name in ("db", "inbox", "outbox"):
        path = Path(getattr(args, name))
        if not path.is_absolute():
            raise WorkerError("unsafe_local_path")
        try:
            relative = path.relative_to(repo / "var")
        except ValueError:
            raise WorkerError("unsafe_local_path") from None
        if not relative.parts or ".." in relative.parts:
            raise WorkerError("unsafe_local_path")
        current = repo / "var"
        for component in ("", *relative.parts):
            if component:
                current = current / component
            info = current.lstat()
            expected_file = name == "db" and current == path
            if (info.st_uid != os.getuid() or stat.S_ISLNK(info.st_mode)
                    or (not stat.S_ISREG(info.st_mode) if expected_file else not stat.S_ISDIR(info.st_mode))
                    or stat.S_IMODE(info.st_mode) != (0o600 if expected_file else 0o700)):
                raise WorkerError("unsafe_local_path")
        paths[name] = path
    if not paths["outbox"].is_relative_to(repo / "var/outbox"):
        raise WorkerError("unsafe_outbox")
    return repo, paths


def health_command(repo):
    checker = repo / "scripts/check-system.py"
    info = checker.lstat()
    python = repo / "research/engine/.venv/bin/python"
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or not python.is_file() or not os.access(python, os.X_OK)):
        raise WorkerError("health_tool_unavailable")
    return [str(python), "-B", str(checker), "--repo-root", str(repo), "--json"]


def health_evidence(output, exit_code):
    """Only constant check names and booleans can leave the local health channel."""
    if len(output) > 256 * 1024:
        raise WorkerError("invalid_health_evidence")
    try:
        record = parse_json_strict(output)
        checks = record["checks"]
        observed = dt.datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
        if observed.tzinfo is None or not -60 <= (dt.datetime.now(dt.timezone.utc) - observed).total_seconds() <= 120:
            raise ValueError
        if (type(record["schema_version"]) is not int or record["schema_version"] != 1
                or record["verdict"] not in {"PASS", "FAIL"} or not isinstance(checks, list)
                or not 1 <= len(checks) <= len(CHECK_NAMES)):
            raise ValueError
        safe = {}
        for item in checks:
            if item["name"] not in CHECK_NAMES or item["name"] in safe or type(item["ok"]) is not bool:
                raise ValueError
            safe[item["name"]] = item["ok"]
        if not (CHECK_NAMES - {"data_freshness"}).issubset(safe):
            raise ValueError
        normalized = [{"name": name, "ok": safe.get(name, False)} for name in sorted(CHECK_NAMES)]
        healthy = record["verdict"] == "PASS" and all(item["ok"] for item in normalized)
        if (exit_code == 0) != healthy or exit_code not in (0, 1):
            raise ValueError
        return healthy, normalized, observed.astimezone(dt.timezone.utc).isoformat(timespec="seconds")
    except (AttributeError, KeyError, TypeError, ValueError):
        raise WorkerError("invalid_health_evidence") from None


def verified_result(database, task, outbox):
    result_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"trading-os-result:{task['id']}"))
    result = database.get_message(result_id)
    if (task["result_message_id"] != result_id or result is None
            or not database._chief_result_matches_task(task, result)):
        raise WorkerError("result_readback_failed")
    payload = parse_json_strict(result["payload_json"].encode())
    if sha256_bytes(canonical_bytes(payload)) != result["payload_sha256"]:
        raise WorkerError("result_readback_failed")
    uri = urlparse(result["source_uri"])
    path = Path(unquote(uri.path))
    if uri.scheme != "file" or uri.netloc or not path.is_relative_to(outbox) or ".." in path.parts:
        raise WorkerError("result_readback_failed")
    # No symlink component or special file can redirect or block result readback.
    current = outbox
    for part in path.relative_to(outbox).parts:
        current = current / part
        if current.is_symlink():
            raise WorkerError("result_readback_failed")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 256 * 1024):
            raise WorkerError("result_readback_failed")
        raw = stream.read(256 * 1024 + 1)
    if (len(raw) > 256 * 1024 or sha256_bytes(raw) != result["raw_sha256"]
            or canonical_bytes(parse_json_strict(raw)) != canonical_bytes(payload)):
        raise WorkerError("result_readback_failed")
    verdict = payload["metadata"]["result"]["verification_verdict"]
    if verdict not in {"ALIGNED", "BLOCKED"}:
        raise WorkerError("result_readback_failed")
    return {"ok": verdict == "ALIGNED", "task_id": task["id"], "result_id": result_id,
            "result_path": str(path), "verification_verdict": verdict}


def run_worker(args):
    repo, paths = selected_paths(args)
    database = Store(paths["db"], repo / "migrations")
    binding = validate_task(database, repo, args.task_id, args.reviewed_sha256)
    task = database.get_message(args.task_id)
    payload = parse_json_strict(task["payload_json"].encode())
    if (payload["metadata"].get("local_action") != "health"
            or binding["owned_paths"] != ["var/outbox"] or args.action != "health"):
        raise WorkerError("unsupported_task_action")
    if task["status"] in {"completed", "failed"}:
        result = verified_result(database, task, paths["outbox"])
        result["duplicate"] = True
        return result
    if task["status"] != "received":
        raise WorkerError("task_not_available")
    command = health_command(repo)
    before = snapshot(repo)
    claimed = accept_task(database, repo, args.task_id, args.reviewed_sha256)
    healthy, checks, observed_at, failure, exit_code = False, [], None, None, 125
    try:
        process = subprocess.run(command, cwd=repo, env=child_environment(),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 timeout=TIMEOUT_SECONDS, check=False, shell=False)
        exit_code = process.returncode
        healthy, checks, observed_at = health_evidence(process.stdout, exit_code)
    except subprocess.TimeoutExpired:
        failure, exit_code = "health_check_timeout", 124
    except (OSError, WorkerError):
        failure = "health_check_evidence_unavailable"
    after = snapshot(repo)
    unchanged = before == after
    aligned = healthy and unchanged and failure is None
    report = {
        "subject": "Local health verification", "body": "Health verification passed." if aligned else "Health verification blocked.",
        "changed_files": [],
        "commands": [{"command": "project-python scripts/check-system.py --repo-root <repository> --json",
                      "exit_code": exit_code, "summary": "PASS" if aligned else "BLOCKED"}],
        "git_state": {"head_before": before["head"], "head_after": after["head"],
                      "checkout_unchanged": unchanged, "action": "health", "checks": checks,
                      "observed_at": observed_at},
        "skipped_checks": ["Cloud body and required_tests are not executable commands.", "No commit, push, deployment or trading action."],
        "risks": ([failure] if failure else []) + ([] if unchanged else ["checkout_changed_during_health_check"]),
        "verification_verdict": "ALIGNED" if aligned else "BLOCKED",
        "next_safe_step": "Read the correlated result before further work." if aligned else "Review the local blocked checks before retrying.",
    }
    # Existing bridge result generation supplies immutable UUID/correlation/readback.
    old = {name: getattr(cli, name) for name in ("ROOT", "DEFAULT_DB", "INBOX", "OUTBOX", "store")}
    temporary = None
    try:
        cli.ROOT, cli.DEFAULT_DB = repo, paths["db"]
        cli.INBOX, cli.OUTBOX = paths["inbox"], paths["outbox"]
        cli.store = lambda: database  # Database setup/migrations are a separate action.
        with tempfile.NamedTemporaryFile(dir=paths["outbox"], prefix=".local-chief-", suffix=".json", delete=False) as stream:
            temporary = Path(stream.name)
            os.fchmod(stream.fileno(), 0o600)
            stream.write(canonical_bytes(report))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = cli.command_result(argparse.Namespace(task_id=args.task_id, report=str(temporary)))
        if status:
            raise WorkerError("result_publication_failed")
        task = database.get_message(claimed["id"])
        result = verified_result(database, task, paths["outbox"])
        if snapshot(repo) != after:
            raise WorkerError("checkout_changed_after_result")
        if not database.update_status(task["id"], "completed" if aligned else "failed", worker="chief-engineer"):
            raise WorkerError("terminal_status_failed")
        result["duplicate"] = False
        return result
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        for name, value in old.items():
            setattr(cli, name, value)


def main(argv=None):
    parser = Parser(description=__doc__)
    for name in ("task-id", "reviewed-sha256", "repo", "db", "inbox", "outbox"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--action", choices=["health"], default="health")
    try:
        result = run_worker(parser.parse_args(argv))
    except WorkerError as error:
        result = {"ok": False, "error": str(error)}
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, subprocess.SubprocessError):
        result = {"ok": False, "error": "local_task_rejected"}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
