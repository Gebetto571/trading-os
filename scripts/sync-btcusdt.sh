#!/bin/bash
set -euo pipefail

readonly REPOSITORY_ROOT="/Users/scm/Projects/trading-os"
readonly RELEASE_BINARY="${REPOSITORY_ROOT}/target/release/market-data-import"
readonly ENVIRONMENT_FILE="${REPOSITORY_ROOT}/.env"
readonly HEALTH_DIRECTORY="${TRADING_OS_MARKET_DATA_HEALTH_DIR:-${REPOSITORY_ROOT}/data/health/btcusdt}"

publish_boot_failure() {
    local message="$1"
    local observed_at
    local record
    local temporary
    observed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    record="{\"schema_version\":1,\"observed_at\":\"${observed_at}\",\"status\":\"failed\",\"database_reachable\":false,\"symbol\":\"BTCUSDT\",\"rows_fetched\":0,\"rows_inserted\":0,\"rows_repaired\":0,\"gaps_remaining\":0,\"partitions_verified\":0,\"duration_ms\":0,\"error\":\"${message}\"}"
    umask 077
    mkdir -p "${HEALTH_DIRECTORY}"
    chmod 700 "${HEALTH_DIRECTORY}"
    temporary="$(mktemp "${HEALTH_DIRECTORY}/.latest.json.XXXXXX.part")"
    printf '%s\n' "${record}" >"${temporary}"
    chmod 600 "${temporary}"
    mv -f "${temporary}" "${HEALTH_DIRECTORY}/latest.json"
    printf '%s\n' "${record}" >>"${HEALTH_DIRECTORY}/history.jsonl"
    chmod 600 "${HEALTH_DIRECTORY}/history.jsonl"
    printf '%s\n' "${record}"
}

cd "${REPOSITORY_ROOT}"

if [[ ! -x "${RELEASE_BINARY}" ]]; then
    publish_boot_failure "release binary unavailable"
    exit 69
fi

if [[ -r "${ENVIRONMENT_FILE}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "${ENVIRONMENT_FILE}" >/dev/null
    set +a
fi

export RUST_LOG="${RUST_LOG:-warn}"
export TRADING_OS_MARKET_DATA_HEALTH_DIR="${HEALTH_DIRECTORY}"

exec "${RELEASE_BINARY}" sync \
    --symbol BTCUSDT \
    --interval 1m \
    --start 2023-08-03T00:00:00Z \
    --end latest-closed \
    --parquet-root "${REPOSITORY_ROOT}/data/parquet" \
    --cache-root "${REPOSITORY_ROOT}/data/cache"
