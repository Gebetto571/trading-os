#!/bin/bash
# Logical backups never include .env and are kept outside the Git checkout.
set -euo pipefail
umask 077
REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
DESTINATION="${HOME}/TradingOSBackups"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --destination) [[ $# -ge 2 ]] || exit 64; DESTINATION="$2"; shift 2 ;;
        --help) printf '%s\n' 'Usage: scripts/backup-database.sh [--destination DIRECTORY]'; exit 0 ;;
        *) printf '%s\n' 'Unknown backup option.' >&2; exit 64 ;;
    esac
done
# shellcheck source=scripts/lib/market-data.sh
source "${REPOSITORY_ROOT}/scripts/lib/market-data.sh"
tos_init "${REPOSITORY_ROOT}"
tos_load_env
PYTHON="$(tos_python)"
DESTINATION="$("${PYTHON}" - "${DESTINATION}" "${REPOSITORY_ROOT}" <<'PY'
import os, pathlib, stat, sys
path = pathlib.Path(sys.argv[1]).expanduser().absolute()
root = pathlib.Path(sys.argv[2]).resolve()
resolved = path.resolve()
if resolved == root or root in resolved.parents:
    raise SystemExit('Backups must be outside the repository.')
for item in (path, *path.parents):
    if item.is_symlink():
        raise SystemExit('Backup directory must not use symlinks.')
path.mkdir(parents=True, exist_ok=True, mode=0o700)
metadata = path.stat()
if metadata.st_uid != os.getuid() or not stat.S_ISDIR(metadata.st_mode):
    raise SystemExit('Backup directory must be owned by the current user.')
path.chmod(0o700)
print(path)
PY
)"
BACKUP_DIRECTORY="$(mktemp -d "${DESTINATION}/postgres-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"
chmod 700 "${BACKUP_DIRECTORY}"
ARCHIVE="${BACKUP_DIRECTORY}/market-data.dump"
PARTIAL="${ARCHIVE}.part"
COMPLETED=0
finish() {
    local code=$?
    trap - EXIT INT TERM
    if [[ "${COMPLETED}" != 1 ]]; then
        rm -f -- "${PARTIAL}"
        printf '%s\n' "Backup incomplete; retained directory: ${BACKUP_DIRECTORY}" >&2
    fi
    exit "${code}"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
COMPOSE=(docker compose --env-file "${TOS_ENV_FILE}" -f "${REPOSITORY_ROOT}/compose.market-data.yml")
"${COMPOSE[@]}" exec -T postgres pg_dump --format=custom --no-owner --no-acl \
    --username="${POSTGRES_USER:?}" --dbname="${POSTGRES_DB:?}" >"${PARTIAL}" 2>/dev/null || {
    printf '%s\n' 'Database dump failed.' >&2; exit 1;
}
[[ -s "${PARTIAL}" ]] || { printf '%s\n' 'Database dump is empty.' >&2; exit 1; }
chmod 600 "${PARTIAL}"
"${COMPOSE[@]}" exec -T postgres pg_restore --list <"${PARTIAL}" >"${BACKUP_DIRECTORY}/contents.list.part" 2>/dev/null || {
    printf '%s\n' 'Database dump archive validation failed.' >&2; exit 1;
}
mv -- "${PARTIAL}" "${ARCHIVE}"
mv -- "${BACKUP_DIRECTORY}/contents.list.part" "${BACKUP_DIRECTORY}/contents.list"
"${PYTHON}" - "${ARCHIVE}" "${REPOSITORY_ROOT}" <<'PY'
import datetime, hashlib, json, os, pathlib, subprocess, sys
archive = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
with archive.open('rb') as stream:
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(block)
sha = digest.hexdigest()
(archive.parent / 'market-data.dump.sha256').write_text(sha + '  market-data.dump\n')
try:
    commit = subprocess.run(['git', '-C', sys.argv[2], 'rev-parse', 'HEAD'],
                            check=True, capture_output=True, text=True).stdout.strip()
except (OSError, subprocess.SubprocessError):
    commit = None
record = dict(schema_version=1, created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              archive='market-data.dump', bytes=archive.stat().st_size, sha256=sha,
              archive_list_verified=True, restore_verified=False, source_commit=commit,
              storage_device='not_verified', separate_physical_disk_verified=False)
(archive.parent / 'manifest.json').write_text(json.dumps(record, indent=2) + '\n')
for path in archive.parent.iterdir():
    if path.is_file():
        path.chmod(0o600)
print('Backup created and archive validated: ' + str(archive.parent))
print('A separate restore test and another physical disk remain independent checks.')
PY
COMPLETED=1
