# Development and CI

Use CPython 3.12/3.13. The source package lives under `src/`; core owns JSON schemas and web owns static assets. Install the development profile from the checkout:

```bash
python -m pip install -r requirements/dev.txt
python -m pip install --no-deps --no-build-isolation -e '.[web,dev]'
python -m pip check
python scripts/check-dependencies.py
python -m pytest -m 'not ffmpeg'
python -m build --no-isolation
python scripts/check-distributions.py
```

Run these inside a venv. The developer profile includes both web and build dependencies. Merely installing the `dev` extra does not include the `web` extra or lock transitive dependencies; the requirements profile is the reproducible entry point.

## Dependency locks

`requirements/runtime.txt`, `web.txt`, `dev.txt`, and `build.txt` pin exact versions, including the applicable transitive dependencies. Web includes runtime; dev includes web and build. Platform markers retain Windows-only colorama. NumPy 2.5.3 requires Python >=3.12 and SciPy 1.18.1 accepts NumPy >=2.0,<2.8 according to PyPI metadata. These were selected together; newer versions are not silently substituted. Metadata sources: [NumPy](https://pypi.org/project/numpy/2.5.3/), [SciPy](https://pypi.org/project/scipy/1.18.1/), [FastAPI](https://pypi.org/project/fastapi/0.141.1/), [jsonschema](https://pypi.org/project/jsonschema/4.26.0/).

The locks pin versions, not artifact hashes; they are not a hash-verified supply-chain lock. FFmpeg and platform system libraries are external and not fixed by pip. Record their versions with performance or integration results. `pyproject.toml` pins direct application dependencies and build backend; installers also pin the complete build-tool profile before a build without isolation.

For updates, inspect PyPI `Requires-Python` and `Requires-Dist` for every changed dependency, update direct pins and the transitive closure together, resolve/install in clean environments, run `pip check` and `scripts/check-dependencies.py`, then run the full six-entry CI matrix. The checker verifies installed exact versions, agreement with pyproject, and each profile's active transitive closure. Retain OS markers. Check wheel availability on the target platforms, not only resolver success. Avoid refreshing locks by blindly copying a globally installed `pip freeze`.

## CI

`.github/workflows/ci.yml` runs on pushes and pull requests with a 3 OS x 2 Python matrix. Each entry installs the dev lock and editable package, runs `pip check` and pytest excluding tests marked `ffmpeg`, builds an sdist and a wheel, installs the wheel, and verifies the CLI entry point, JSON schemas and static index outside the checkout. It also syntax-checks Bash scripts and, on Windows, PowerShell scripts.

FFmpeg installation is an opt-in manual workflow input, `ffmpeg_smoke`. That Ubuntu job installs FFmpeg with apt, runs doctor, and executes `scripts/smoke-ffmpeg.py`. The smoke invokes `sys.executable -m acoustic_sync`, requiring only FFmpeg and ffprobe on PATH. It creates two synthetic audio files and asserts one group, zero orphans, an exact one-second camera offset, and xmeml4 clipitems. This fixture does not establish general matching accuracy, all-stream preservation, scalability or Premiere compatibility. The revised smoke awaits execution. Tests that require FFmpeg should use the `ffmpeg` marker and skip clearly when required binaries are absent.

The complete local suite passed 145 tests plus 28 subtests, with two upstream deprecation warnings involving Starlette/httpx and AnyIO. Browser QA passed for the 13-source rational-FPS partial-result workflow. Local `pip check`, exact dependency-closure validation, distribution build and package-asset checks passed. The Windows dev installer succeeded against an existing local venv without system dependency provisioning; macOS/Linux installers have only been syntax-checked. These results do not establish a successful CI matrix run. See the [validation report](validation-report.md), [installation scope](installation.md), and [Premiere checklist](premiere-validation.md).

## Measured matching benchmark

The saved `results/benchmark_report.json` records this single local measurement:

| Measure | Result |
| --- | --- |
| Scope | Module B matching only; deterministic mono PCM sources |
| Inputs | 100 sources, eight seconds each; 800 source-seconds total |
| Construction | Five overlapping clips per group |
| Output | 20 groups, zero unmatched sources |
| Elapsed | 7.156 seconds (internal matching statistic: 7.094 seconds) |
| Peak process RSS | 140.18 MiB (report field `peak_rss_mb`) |
| Work | 158,937 fingerprints, 100 reference streams, 140 accepted matches |
| Environment | Windows 11 build 26100, Python 3.12.10, 16 logical CPUs; AMD64 Family 25 Model 97 Stepping 2 |

This measurement excludes media extraction, XML export and Premiere import. It is not a long-recording, end-to-end, repeated-run or cross-platform performance result. Do not extrapolate it to arbitrary recordings or treat the generated group construction as real-world accuracy evidence.

## Package checks

`python scripts/check-package.py` verifies installed schemas and web assets; run from outside the checkout after installing a built wheel to avoid source-tree masking. Build both distribution formats so the wheel rebuilt from the sdist exercises resource inclusion. `MANIFEST.in` includes docs, installer/launcher and verification scripts, requirements, tests and fixture generators, JSON schemas and static web assets in the source distribution. The wheel contains only `acoustic_sync` and distribution metadata; tests and fixture generators are intentionally excluded.

`python scripts/check-distributions.py` checks this separation and required source-release files; CI runs it after building. Generated private media, extracted references, SQLite databases, bytecode and local runtime downloads do not belong in release artifacts.

## Design boundaries

Maintain JSON-only stage boundaries, deterministic sample offsets, finite JSON numbers, strong-edge graph consistency and readable-media retention. Keep web imports optional. Add meaningful tests for timing math, multistream origins, cycle rejection, cancellation/cleanup containment, malformed contracts and export channel/link structure. Future work such as calibrated scoring or drift correction needs explicit acceptance criteria before being described as implemented.
