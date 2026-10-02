#!/bin/bash
set -euo pipefail
umask 077

# Establish a safe failure channel before reading config or any helper.
TOS_RUNTIME_ROOT="${TRADING_OS_RUNTIME_ROOT:-${HOME}/Library/Application Support/TradingOS/market-data}"
TOS_HEALTH_DIRECTORY="${TRADING_OS_MARKET_DATA_HEALTH_DIR:-${TOS_RUNTIME_ROOT}/health}"
failure_code=boot_failed
child_pid=""
boot_failure() {
    if declare -F tos_health_failure >/dev/null; then
        tos_health_failure "${failure_code}" 2>/dev/null || true
    else
        local record temporary
        record="{\"schema_version\":1,\"observed_at\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"status\":\"failed\",\"database_reachable\":false,\"symbol\":\"BTCUSDT\",\"error\":\"boot_failed\"}"
        if [[ ! -L "${TOS_HEALTH_DIRECTORY}" ]] && mkdir -p "${TOS_HEALTH_DIRECTORY}" 2>/dev/null; then
            temporary="$(mktemp "${TOS_HEALTH_DIRECTORY}/.latest.json.XXXXXX")" || return 0
            printf '%s\n' "${record}" >"${temporary}"
            chmod 600 "${temporary}"
            mv -f "${temporary}" "${TOS_HEALTH_DIRECTORY}/latest.json"
        fi
        printf '%s\n' "${record}"
    fi
}
finish() {
    local result=$?
    trap - EXIT
    if [[ "${result}" -ne 0 ]]; then boot_failure; fi
    exit "${result}"
}
stop() {
    failure_code=collector_interrupted
    if [[ -n "${child_pid}" ]]; then kill -TERM "${child_pid}" 2>/dev/null || true; fi
    exit 143
}
trap finish EXIT
trap stop TERM INT

repository="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=scripts/lib/market-data.sh
source "${repository}/scripts/lib/market-data.sh"
tos_init "${repository}"
failure_code=environment_rejected
tos_load_env >/dev/null 2>&1
tos_python_action validate-env >/dev/null 2>&1
failure_code=release_unavailable
binary="$(tos_release_path)" 2>/dev/null
failure_code=working_directory_unavailable
cd "${TOS_REPOSITORY_ROOT}"
export RUST_LOG="${RUST_LOG:-warn}"
export TRADING_OS_MARKET_DATA_HEALTH_DIR="${TOS_HEALTH_DIRECTORY}"
started="$(date +%s)"
failure_code=collector_failed

# Raw executable diagnostics may contain database credentials. Health JSON is
# the supported diagnostic channel; stdout/stderr are never persisted here.
"${binary}" sync --symbol BTCUSDT --interval 1m \
    --start 2023-08-03T00:00:00Z --end latest-closed \
    --parquet-root "${TOS_REPOSITORY_ROOT}/data/parquet" \
    --cache-root "${TOS_REPOSITORY_ROOT}/data/cache" \
    --health-root "${TOS_HEALTH_DIRECTORY}" >/dev/null 2>&1 &
child_pid=$!
wait "${child_pid}"
child_pid=""
failure_code=health_record_unavailable
tos_python_action validate-health "${started}" >/dev/null 2>&1
printf '%s\n' 'Market-data attempt completed; health record updated.'
