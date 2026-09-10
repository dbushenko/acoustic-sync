#!/usr/bin/env bash
# macOS Finder launcher (chmod +x run-web.command once).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$ROOT/scripts/run-web.sh" "$@" || { result=$?; read -r -p 'Press Return to close.'; exit "$result"; }
