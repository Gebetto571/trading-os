#!/bin/bash
set -euo pipefail
umask 077

repository="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "${repository}/scripts/lib/market-data.sh"
tos_init "${repository}"
config_only=false
activate_agent=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config-only) config_only=true ;;
        --activate-agent) activate_agent=true ;;
        --help)
            printf '%s\n' 'Usage: setup-mac-mini.sh [--config-only] [--activate-agent]'
            printf '%s\n' 'Prepare private config, pinned Python environment and user LaunchAgent.'
            printf '%s\n' 'No database or collector starts unless --activate-agent is explicit.'
            exit 0 ;;
        *) printf '%s\n' 'Unknown setup option.' >&2; exit 64 ;;
    esac
    shift
done

# Configure creates a missing example with O_EXCL and never replaces an .env.
tos_python_action configure
if ! "${config_only}"; then
    version="$("${TOS_PYTHON}" -c 'import platform; print(platform.python_version())')"
    [[ "${version}" == 3.12.14 ]] || { printf '%s\n' 'Python 3.12.14 is required; existing environment was preserved.' >&2; exit 69; }
    uv="$(command -v uv || true)"
    if [[ -z "${uv}" && -x /opt/homebrew/bin/uv ]]; then uv=/opt/homebrew/bin/uv; fi
    [[ -x "${uv}" ]] || { printf '%s\n' 'uv is required for explicit environment setup.' >&2; exit 69; }
    venv="${repository}/research/engine/.venv"
    if [[ ! -e "${venv}" ]]; then
        "${uv}" venv --python "${TOS_PYTHON}" "${venv}"
    fi
    [[ ! -L "${venv}" && -x "${venv}/bin/python" ]] || { printf '%s\n' 'Existing virtual environment is invalid; preserved for inspection.' >&2; exit 69; }
    [[ "$("${venv}/bin/python" -c 'import platform; print(platform.python_version())')" == 3.12.14 ]] ||
        { printf '%s\n' 'Existing Python differs; environment preserved.' >&2; exit 69; }
    UV_CACHE_DIR="${venv}/.uv-cache" "${uv}" pip install --python "${venv}/bin/python" \
        -r "${repository}/research/engine/requirements.txt" jsonschema==4.23.0
fi
if "${activate_agent}"; then
    [[ "$(uname -s)" == Darwin ]] || { printf '%s\n' 'LaunchAgent activation requires macOS.' >&2; exit 69; }
    project_python="${repository}/research/engine/.venv/bin/python"
    [[ -x "${project_python}" && "$("${project_python}" -c 'import platform; print(platform.python_version())')" == 3.12.14 ]] ||
        { printf '%s\n' 'Prepare the pinned project Python before activating the agent.' >&2; exit 69; }
    tos_python_action validate-env
    tos_release_path >/dev/null
    service="gui/$(id -u)/com.tradingos.market-data.btcusdt-sync"
    if launchctl print "${service}" >/dev/null 2>&1; then
        printf '%s\n' 'Existing collector remains loaded; no restart performed.'
    else
        launchctl bootstrap "gui/$(id -u)" "${HOME}/Library/LaunchAgents/com.tradingos.market-data.btcusdt-sync.plist"
        printf '%s\n' 'Collector LaunchAgent activated.'
    fi
fi
