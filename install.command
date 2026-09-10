#!/usr/bin/env bash
# macOS Finder installer (chmod +x install.command once).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$ROOT/install.sh" "$@" || { result=$?; read -r -p 'Press Return to close.'; exit "$result"; }
read -r -p 'Installation complete. Press Return to close.'
