#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE=web
INSTALL_SYSTEM_DEPS=0
PYTHON_BIN="${PYTHON:-}"
while (($#)); do
  case "$1" in
    --profile) PROFILE="${2:?--profile requires runtime, web, or dev}"; shift 2 ;;
    --python) PYTHON_BIN="${2:?--python requires an executable}"; shift 2 ;;
    --install-system-deps) INSTALL_SYSTEM_DEPS=1; shift ;;
    -h|--help) echo 'Usage: bash scripts/install.sh [--profile runtime|web|dev] [--python /path/python3] [--install-system-deps]'; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$PROFILE" in runtime|web|dev) ;; *) echo 'Invalid profile' >&2; exit 2 ;; esac
find_python() {
  local candidate
  if [[ -n "$PYTHON_BIN" ]]; then
    "$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3,12)' >/dev/null 2>&1 && return 0
    return 1
  fi
  for candidate in python3.13 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info >= (3,12)' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"; return 0
    fi
  done
  return 1
}
if ((INSTALL_SYSTEM_DEPS)); then
  case "$(uname -s)" in
    Darwin)
      command -v brew >/dev/null 2>&1 || { echo 'Install Homebrew first, or install Python and FFmpeg manually.' >&2; exit 1; }
      if ! find_python; then brew install python@3.13; PYTHON_BIN="$(brew --prefix python@3.13)/bin/python3.13"; fi
      if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then brew install ffmpeg; fi
      ;;
    Linux)
      command -v apt-get >/dev/null 2>&1 || { echo 'Automatic Linux setup supports apt only. Install Python >=3.12, venv, FFmpeg manually.' >&2; exit 1; }
      SUDO=()
      if ((EUID != 0)); then command -v sudo >/dev/null 2>&1 || { echo 'sudo is required for apt setup.' >&2; exit 1; }; SUDO=(sudo); fi
      "${SUDO[@]}" apt-get update
      "${SUDO[@]}" apt-get install -y python3 python3-venv ffmpeg
      ;;
    *) echo 'Automatic dependency installation supports macOS and apt-based Linux.' >&2; exit 1 ;;
  esac
fi
find_python || { echo 'Python >=3.12 is required. Use --python /path/to/python3.12. Some apt distributions ship older Python; upgrade or provision 3.12/3.13 separately.' >&2; exit 1; }
for tool in ffmpeg ffprobe; do
  command -v "$tool" >/dev/null 2>&1 || { echo "$tool is missing from PATH. Install FFmpeg or use --install-system-deps." >&2; exit 1; }
  "$tool" -version
done
VENV="$ROOT/.venv"
if [[ -e "$VENV" ]]; then
  [[ -x "$VENV/bin/python" ]] || { echo "$VENV exists but is not a usable Unix venv. Move it aside manually." >&2; exit 1; }
else
  "$PYTHON_BIN" -m venv "$VENV"
fi
"$VENV/bin/python" -c 'import sys; assert sys.version_info >= (3,12), "Python >=3.12 required"'
"$VENV/bin/python" -m pip install -r "$ROOT/requirements/build.txt"
"$VENV/bin/python" -m pip install -r "$ROOT/requirements/$PROFILE.txt"
"$VENV/bin/python" -m pip install --no-deps --no-build-isolation -e "$ROOT"
"$VENV/bin/python" -m pip check
"$VENV/bin/acoustic-sync" doctor
echo "Installed $PROFILE profile. CLI: $VENV/bin/acoustic-sync"
