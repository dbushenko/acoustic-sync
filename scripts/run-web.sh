#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8765
STATE_ARGS=(--state-dir "$ROOT/results/web-state")
BROWSER_ARGS=(--open-browser)
if (($#)) && [[ "$1" != --* ]]; then PORT="$1"; shift; fi
while (($#)); do
  case "$1" in
    --state-dir) STATE_ARGS=(--state-dir "${2:?--state-dir requires a directory}"); shift 2 ;;
    --no-browser) BROWSER_ARGS=(); shift ;;
    --help) echo 'Usage: bash run-web.sh [port: 1-65535] [--state-dir directory] [--no-browser]'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ ! "$PORT" =~ ^[0-9]{1,5}$ ]] || ((10#$PORT < 1 || 10#$PORT > 65535)); then
  echo 'Usage: bash scripts/run-web.sh [port: 1-65535] [--state-dir directory]' >&2; exit 2
fi
[[ -x "$ROOT/.venv/bin/acoustic-sync" ]] || { echo 'Run bash scripts/install.sh --profile web first.' >&2; exit 1; }
cd -- "$ROOT"
echo "Acoustic Sync: http://127.0.0.1:$PORT/ (Ctrl+C to stop)"
exec "$ROOT/.venv/bin/acoustic-sync" serve --port "$PORT" "${STATE_ARGS[@]}" "${BROWSER_ARGS[@]}"
