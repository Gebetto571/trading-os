"""Explicit, local admission of one reviewed task; never executes task text.

The reviewed digest is the canonical JSON ``payload_sha256`` stored by the bridge,
not a hash of a JSON file's whitespace. Supplying it is a local operator action;
the incoming ``approval_state`` field alone never calls or authorizes this gate.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import uuid
from pathlib import Path, PurePosixPath

from .store import InvalidTransition, OwnershipConflict, Store
from .validation import (
    canonical_bytes, load_conversation_map, parse_json_strict, sha256_bytes,
    validate_message,
)


class AcceptanceError(ValueError):
    """A reviewed task is not safe to claim in this checkout."""


_MAP = Path(__file__).resolve().parents[1] / "schemas/conversation-map.json"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_BINDING_KEYS = {
    "active_writer_principal", "canonical_lane", "expected_base_commit",
    "exact_owned_paths",
}


def _git(repo: Path, *arguments: str) -> bytes:
    # A caller's GIT_DIR/INDEX_FILE/config must not redirect the fixed repository.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo),
             *arguments],
            cwd=repo, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise AcceptanceError("Local Git verification could not run.") from error
    if result.returncode:
        # Git diagnostics may contain local paths or configuration; do not relay them.
        raise AcceptanceError("Local Git verification failed.")
    return result.stdout


def _checkout(repo: Path, expected_commit: str) -> Path:
    try:
        if not repo.is_absolute():
            raise AcceptanceError("An absolute repository path is required.")
        root = repo.resolve(strict=True)
        if not root.is_dir():
            raise AcceptanceError("Repository path must be a directory.")
        git_root = Path(os.fsdecode(_git(root, "rev-parse", "--show-toplevel")).rstrip("\n"))
        if git_root.resolve(strict=True) != root:
            raise AcceptanceError("Repository path must be the exact Git root.")
        head = _git(root, "rev-parse", "--verify", "HEAD^{commit}").decode("ascii").strip()
        if head != expected_commit:
            raise AcceptanceError("Local HEAD differs from the reviewed task base.")
        if _git(root, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=none", "-z"):
            raise AcceptanceError("Local checkout must be clean before acceptance.")
        return root
    except (OSError, UnicodeError) as error:
        raise AcceptanceError("Repository verification failed.") from error


def _owned_paths(value: object, root: Path) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 200:
        raise AcceptanceError("A nonempty frozen path list is required.")
    normalized = []
    for raw in value:
        if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
            raise AcceptanceError("Frozen paths must be canonical repository-relative paths.")
        path = PurePosixPath(raw)
        if path.is_absolute() or raw != path.as_posix() or raw == "." or ".." in path.parts:
            raise AcceptanceError("Frozen paths must not include the repository root or traversal.")
        parts = tuple(part.casefold() for part in path.parts)
        if parts[0] == "sources" or any(
            part == ".git" or part == ".env" or part.startswith(".env.") for part in parts
        ):
            raise AcceptanceError("Frozen scope includes a protected path.")
        candidate = root
        for part in path.parts:
            candidate = candidate / part
            if candidate.is_symlink():
                raise AcceptanceError("Frozen scope must not traverse symbolic links.")
        try:
            candidate.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError) as error:
            raise AcceptanceError("Frozen scope escapes the repository.") from error
        normalized.append(raw)
    if len(set(normalized)) != len(normalized):
        raise AcceptanceError("Frozen scope contains duplicate paths.")
    paths = sorted(normalized)
    for index, left in enumerate(paths):
        if any(right.startswith(left + "/") for right in paths[index + 1:]):
            raise AcceptanceError("Frozen scope contains overlapping paths.")
    return paths


def validate_task(database: Store, repo: Path, task_id: str, reviewed_sha256: str) -> dict:
    """Inspect immutable task identity and the current checkout without claiming it."""
    try:
        if not isinstance(task_id, str) or str(uuid.UUID(task_id)) != task_id:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as error:
        raise AcceptanceError("A canonical task UUID is required.") from error
    if not isinstance(reviewed_sha256, str) or not _DIGEST.fullmatch(reviewed_sha256):
        raise AcceptanceError("The reviewed canonical payload SHA-256 is required.")
    row = database.get_message(task_id)
    if row is None:
        raise AcceptanceError("The exact task is not present in the local bridge.")
    try:
        payload = parse_json_strict(row["payload_json"].encode("utf-8"))
        digest = sha256_bytes(canonical_bytes(payload))
        if digest != reviewed_sha256 or row["payload_sha256"] != digest:
            raise AcceptanceError("Reviewed task hash does not match the stored payload.")
        validate_message(payload, conversation_map=load_conversation_map(_MAP))
        metadata = payload["metadata"]
        binding = metadata["SCOPE_BINDING_MANIFEST"]
        if not isinstance(binding, dict) or set(binding) != _BINDING_KEYS:
            raise AcceptanceError("An exact frozen scope binding is required.")
        base = binding["expected_base_commit"]
        lane = binding["canonical_lane"]
        if not isinstance(base, str) or not _COMMIT.fullmatch(base):
            raise AcceptanceError("Frozen base must be a full Git commit identity.")
        if (
            payload["id"] != task_id or payload["type"] != "task"
            or row["direction"] != "inbound" or row["message_type"] != "task"
            or binding["active_writer_principal"] != "chief-engineer"
            or metadata["authority"] != "chief-engineer"
            or metadata["approval_state"] != "approved_for_local_implementation"
            or lane != metadata["local_lane"]
        ):
            raise AcceptanceError("Task authority or routing does not match the frozen binding.")
        root = _checkout(Path(repo), base)
        paths = _owned_paths(metadata["FROZEN_OWNED_PATHS"], root)
        if paths != _owned_paths(binding["exact_owned_paths"], root):
            raise AcceptanceError("Frozen scope lists do not match.")
        return {
            "id": task_id, "payload_sha256": digest, "base_commit": base,
            "local_lane": lane, "owned_paths": paths,
        }
    except AcceptanceError:
        raise
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise AcceptanceError("Task payload or frozen binding is invalid.") from error


def accept_task(
    database: Store, repo: Path, task_id: str, reviewed_sha256: str, lease_seconds: int = 1800,
) -> sqlite3.Row:
    """Claim only this locally selected, reviewed task using the existing store gate.

    No code, shell command, test, service, PAPER/LIVE action or permission grant is
    derived from the task body. The caller remains responsible for its authorized
    action and for checking the checkout again immediately before any later write.
    """
    if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
        raise AcceptanceError("Acceptance lease must be between 1 and 3600 seconds.")
    task = validate_task(database, repo, task_id, reviewed_sha256)
    try:
        row = database.claim_chief_engineer_task_by_id(
            task_id, task["local_lane"], task["base_commit"], task["owned_paths"],
            lease_seconds, "chief-engineer",
        )
    except (InvalidTransition, OwnershipConflict, ValueError) as error:
        raise AcceptanceError("The exact task cannot be claimed in its current ownership state.") from error
    if row is None:
        raise AcceptanceError("The exact task is no longer available.")
    try:
        # Another local process may move HEAD or edit a path while the SQLite
        # claim is being committed. Never return acceptance for that checkout.
        root = _checkout(Path(repo), task["base_commit"])
        _owned_paths(task["owned_paths"], root)
    except AcceptanceError:
        try:
            database.update_status(
                task_id, "failed", "Checkout changed during local acceptance.",
                worker="chief-engineer",
            )
        except (InvalidTransition, sqlite3.Error):
            pass
        raise AcceptanceError("Checkout changed during local acceptance; execution is blocked.") from None
    return row
