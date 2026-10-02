#!/bin/bash
set -euo pipefail
umask 077

repository="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "${repository}/scripts/lib/market-data.sh"
tos_init "${repository}"
operation="${1:---help}"
if [[ $# -gt 0 ]]; then shift; fi
case "${operation}" in
    build)
        [[ $# -eq 0 ]] || { printf '%s\n' 'Build accepts no extra arguments.' >&2; exit 64; }
        cd "${repository}"
        [[ "$(rustc --version)" == 'rustc 1.88.0 '* ]] ||
            { printf '%s\n' 'Rust 1.88.0 is required.' >&2; exit 69; }
        # Compilation only touches ignored build output, never the active release.
        before="$(tos_source_tree_sha256)"
        before_commit="$(git rev-parse HEAD)"
        cargo build --release --locked -p trading-os-market-data --bin market-data-import
        [[ "${before}" == "$(tos_source_tree_sha256)" ]] ||
            { printf '%s\n' 'Source changed during build; candidate rejected.' >&2; exit 1; }
        tos_python_action candidate "${before}" "${before_commit}" ;;
    activate)
        [[ $# -eq 2 && "$1" == --report ]] ||
            { printf '%s\n' 'Usage: deploy-market-data.sh activate --report PATH' >&2; exit 64; }
        tos_python_action activate "$2" ;;
    rollback)
        [[ $# -eq 0 ]] || exit 64
        tos_python_action rollback ;;
    status)
        [[ $# -eq 0 ]] || exit 64
        tos_release_path ;;
    --help)
        printf '%s\n' 'Usage: deploy-market-data.sh build | activate --report PATH | rollback | status'
        printf '%s\n' 'Build, isolated tests and activation are separate explicit steps.' ;;
    *) printf '%s\n' 'Unknown deployment operation.' >&2; exit 64 ;;
esac
