# Installation

Use 64-bit CPython 3.12 or 3.13 for the tested CI target. Package metadata allows Python >=3.12; later interpreters and other architectures require their own dependency and application validation. FFmpeg and ffprobe must both be on PATH and executable. They are external tools, not pip dependencies.

## Installers

For a full installation including missing system dependencies and the web UI:

| Platform | Install | Start UI |
| --- | --- | --- |
| Windows | Double-click `install.bat` | Double-click `run-web.bat` |
| Linux (apt-based, Python 3.12+ available) | `bash install.sh` | `bash run-web.sh` |
| macOS (Homebrew installed) | `bash install.sh` | `bash run-web.sh` |

On macOS, `chmod +x install.command run-web.command` also enables the Finder double-click launchers. Run installers as your normal user; they request administrative privileges only for system packages. Internet access is required for dependency downloads. Default installation includes Python packages for both the CLI and UI, Python when missing, and FFmpeg/ffprobe. Use `--profile dev` (PowerShell: `-Profile dev`) to include development/test dependencies too.

Launchers open the default browser after the server is ready. Keep their terminal open; Ctrl+C stops the server. Disable browser opening with `run-web.bat -NoBrowser` or `bash run-web.sh --no-browser`. A different port can be selected with `run-web.bat -Port 9000` or `bash run-web.sh 9000`. Defaults are port 8765 and project-local `results/web-state`. On a machine without a desktop browser, open the printed URL manually. The UI remains bound to localhost.

The scripts resolve the checkout from their own location, create `.venv`, install the exact selected dependency profile and build tools, install the checkout in editable mode, run `pip check`, then `acoustic-sync doctor`. They stop on errors. Existing usable venvs are reused; an incompatible or broken venv produces an error rather than being deleted. No activation is needed.

Windows PowerShell:

```powershell
.\scripts\install.ps1 -Profile web
# Optional explicit provisioning through winget:
.\scripts\install.ps1 -Profile web -InstallSystemDeps
# Explicit interpreter if discovery fails:
.\scripts\install.ps1 -Profile dev -Python 'C:\Python313\python.exe'
```

If PowerShell execution policy blocks a trusted checkout, run this one process with `powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Profile web`. The installer does not change persistent execution policy. winget provisioning uses `Python.Python.3.13` and `Gyan.FFmpeg`, accepts their package agreements, and may prompt for elevation. It refreshes PATH; a new terminal may still be needed after provisioning.

macOS / Linux Bash:

```bash
bash scripts/install.sh --profile web
bash scripts/install.sh --profile dev --python /path/to/python3.13
# Optional system package changes:
bash scripts/install.sh --profile web --install-system-deps
```

macOS provisioning requires an existing Homebrew installation and uses `python@3.13` and `ffmpeg`. Linux provisioning supports `apt-get` and installs `python3`, `python3-venv`, and `ffmpeg`, using sudo when necessary. Older distributions may supply Python <3.12; the installer fails the version check and asks for a separately provisioned interpreter. It does not add repositories or PPAs. Other Linux package managers require manual system provisioning. A custom Python may need its matching venv package.

## Manual installation

Create a venv using a suitable interpreter, then run its Python executable:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements/build.txt
.venv/bin/python -m pip install -r requirements/web.txt
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pip check
.venv/bin/acoustic-sync doctor
```

On Windows substitute `py -3.12 -m venv .venv`, `.venv\Scripts\python.exe`, and `.venv\Scripts\acoustic-sync.exe`. Replace `web.txt` with `runtime.txt` or `dev.txt` as needed. `dev.txt` includes web and build dependencies. Always install build tools before using `--no-build-isolation`.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Python not found / too old | Specify a Python 3.12/3.13 executable; reopen the terminal after installation. |
| ffmpeg works but ffprobe fails | Install a complete FFmpeg distribution and put both executables on PATH. |
| venv creation fails | Install the matching Python venv component; check directory permissions. |
| No compatible binary wheel | Prefer the CI target interpreters and standard 64-bit platforms; source builds require additional compilers and libraries. |
| Web dependencies missing | Install `requirements/web.txt` with the same venv Python. |
| Pipeline times out | Check source readability; increase `--timeout`, reduce workers, and inspect retained references/logs. |
| Staged matching cannot find WAVs | Keep the extraction directory until matching finishes; re-extract if it has been removed. |

## Installer validation scope

The Windows installer completed successfully with:

```powershell
.\scripts\install.ps1 -Profile dev -Python 'E:\Work\acoustic-sync\.runtime\python\tools\python.exe'
```

This run reused the existing project-local venv and did not request system dependency installation. `pip check`, exact dependency-closure validation, distribution build and package-asset checks passed. It does not establish clean-machine setup or winget provisioning behavior. macOS/Linux installers passed syntax checks only and have not been executed. Homebrew/apt provisioning and clean-machine behavior remain unverified.
