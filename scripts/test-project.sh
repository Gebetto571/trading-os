#!/bin/bash
# Every full test run owns a separate ephemeral database; .env is never loaded.
set -euo pipefail
umask 077

REPOSITORY_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPOSITORY_ROOT}"
REPORT_FILE="${REPOSITORY_ROOT}/target/test-project/latest.json"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --report-file) [[ $# -ge 2 ]] || exit 64; REPORT_FILE="$2"; shift 2 ;;
        --help) printf '%s\n' 'Usage: scripts/test-project.sh [--report-file PATH]'; exit 0 ;;
        *) printf '%s\n' 'Unknown test option.' >&2; exit 64 ;;
    esac
done
if [[ -n "${DATABASE_URL+x}" ]]; then
    printf '%s\n' 'Refusing inherited DATABASE_URL. Start the test command in a clean shell.' >&2
    exit 64
fi
# shellcheck source=scripts/lib/market-data.sh
source "${REPOSITORY_ROOT}/scripts/lib/market-data.sh"
tos_init "${REPOSITORY_ROOT}"
PYTHON="$(tos_python)"
[[ "$("${PYTHON}" -c 'import sys; print(".".join(map(str,sys.version_info[:3])))')" == '3.12.14' ]] || {
    printf '%s\n' 'Tests require the project Python 3.12.14 environment.' >&2; exit 69;
}
RUST_VERSION="$(rustc --version)"
[[ "${RUST_VERSION}" == 'rustc 1.88.0 '* ]] || {
    printf '%s\n' 'Tests require Rust 1.88.0.' >&2; exit 69;
}
"${PYTHON}" -c 'import polars; from importlib.metadata import version; assert polars.__version__ == "1.35.2"; assert version("jsonschema") == "4.23.0"' || {
    printf '%s\n' 'Pinned test dependencies are unavailable; run setup first.' >&2; exit 69;
}
SOURCE_COMMIT="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
SOURCE_TREE_SHA256="$(tos_source_tree_sha256)"
OWNER="$("${PYTHON}" -c 'import uuid; print(uuid.uuid4().hex)')"
CONTAINER="trading-os-test-${OWNER}"
TEST_PASSWORD="$("${PYTHON}" -c 'import secrets; print(secrets.token_hex(24))')"
POSTGRES_IMAGE='postgres:16.15-alpine'
CREATED=0
VERDICT=FAIL
STAGE=database_start
PYTHON_STATUS=not_run
RUST_STATUS=not_run
CLEANUP=false

finish() {
    local code=$?
    trap - EXIT INT TERM
    if [[ "${CREATED}" == 1 ]]; then
        local actual_owner
        actual_owner="$(docker inspect --format '{{ index .Config.Labels "trading-os.test-owner" }}' "${CONTAINER}" 2>/dev/null || true)"
        if [[ "${actual_owner}" == "${OWNER}" ]] && docker rm -f -v "${CONTAINER}" >/dev/null 2>&1; then
            CLEANUP=true
        else
            VERDICT=FAIL
            STAGE=container_cleanup
            code=1
            printf '%s\n' 'Test container cleanup could not be verified.' >&2
        fi
    else
        CLEANUP=true
    fi
    if ! "${PYTHON}" - "${REPORT_FILE}" "${VERDICT}" "${SOURCE_COMMIT}" "${SOURCE_TREE_SHA256}" "${PYTHON_STATUS}" "${RUST_STATUS}" "${STAGE}" "${POSTGRES_IMAGE}" "${CLEANUP}" "${RUST_VERSION}" <<'PY'
import datetime, json, os, pathlib, stat, sys, tempfile
path = pathlib.Path(sys.argv[1]).absolute()
path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
if path.is_symlink():
    raise SystemExit('Test report path must not be a symlink.')
report = dict(schema_version=1, observed_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
              verdict=sys.argv[2], source_commit=sys.argv[3], source_tree_sha256=sys.argv[4],
              python_version='3.12.14', rust_version=sys.argv[10],
              bridge_research_tests_status=sys.argv[5], rust_tests_status=sys.argv[6],
              stage=sys.argv[7], postgres_image=sys.argv[8], isolated_database=True,
              container_cleanup_verified=sys.argv[9] == 'true')
descriptor, temporary = tempfile.mkstemp(prefix='.test-report-', dir=path.parent)
try:
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
    then
        code=1
    fi
    printf '%s\n' "Test verdict: ${VERDICT}; report: ${REPORT_FILE}"
    exit "${code}"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# Random loopback port, no persistent volume, and an ownership label for cleanup.
CREATED=1
docker run --detach --name "${CONTAINER}" --label "trading-os.test-owner=${OWNER}" \
    -e POSTGRES_USER=trading_os_test -e "POSTGRES_PASSWORD=${TEST_PASSWORD}" \
    -e POSTGRES_DB=trading_os_test -p 127.0.0.1::5432 \
    --tmpfs /var/lib/postgresql/data:rw "${POSTGRES_IMAGE}" >/dev/null
READY=0
for ((attempt=0; attempt<60; attempt++)); do
    if docker exec "${CONTAINER}" pg_isready -U trading_os_test -d trading_os_test >/dev/null 2>&1; then
        READY=1; break
    fi
    sleep 1
done
[[ "${READY}" == 1 ]] || { printf '%s\n' 'Isolated test database did not become ready.' >&2; exit 1; }
PORT="$(docker inspect --format '{{ (index (index .NetworkSettings.Ports "5432/tcp") 0).HostPort }}' "${CONTAINER}")"
[[ "${PORT}" =~ ^[0-9]+$ ]] || { printf '%s\n' 'Invalid isolated database port.' >&2; exit 1; }
export DATABASE_URL="postgres://trading_os_test:${TEST_PASSWORD}@127.0.0.1:${PORT}/trading_os_test"
STAGE=python_tests
"${PYTHON}" -m unittest discover -s tests -v
"${PYTHON}" -m unittest discover -s research/engine/tests -v
PYTHON_STATUS=PASS
STAGE=rust_tests
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-targets --all-features --locked
RUST_STATUS=PASS
STAGE=source_consistency
[[ "$(tos_source_tree_sha256)" == "${SOURCE_TREE_SHA256}" ]] || {
    printf '%s\n' 'Source changed while tests were running; no acceptance report issued.' >&2; exit 1;
}
VERDICT=PASS
STAGE=complete
