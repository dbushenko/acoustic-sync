# Requirements and acceptance criteria

This document defines the target behavior. Source inspection and automated or manual execution are separate evidence; see [architecture](architecture.md) for status.

## Functional requirements

1. Recursively discover supported media without modifying originals. Probe durations, video rate and geometry, every audio stream/channel, and stream timestamps. Keep diagnostic records for unreadable input.
2. Produce 22050 Hz mono PCM16 references for every audio stream by default. Optional 11025 Hz matching must use consistent sample units across the manifest and sync map. Keep each reference's origin relative to primary video, or first audio when video is absent.
3. Find spectrogram peak-pair hash collisions through a SQLite inverted index, aggregate candidate offsets, and verify a bounded shortlist with local FFT correlation. Do not run full all-pairs correlation.
4. Require heuristic confidence >=70 by default plus independent evidence gates. Reject misleading silence, repetitive or ambiguous evidence, inadequate overlap and inconsistent graph constraints. Keep rejected/unmatched clips visible.
5. Build groups from strong edges with cycle consistency. Normalize each group's offsets to nonnegative samples; do not infer timing between disconnected groups. Flag drift and retain original timing without automatic correction.
6. Preserve all readable media, including silent video and media whose reference extraction failed. Export every original audio stream/channel enabled. Unreadable media can only be reported as errors, not fabricated into playable clips.
7. Export FCP7 xmeml version 4. Use rational frame rates, source rate for source in/out, sequence rate for timeline placement, and correct audio/video linking. Pack disconnected groups with two seconds between sections and mark `RELATIVE_TIMING_UNKNOWN`; append orphans under `NOT_SYNCED`.
8. Provide CLI `run` (also the default command), `extract`, `match`, `export`, `serve`, and `doctor`, plus the local optional web UI. Exchange JSON artifacts between extraction, matching and export.

## Operational requirements

- Python >=3.12; CI covers 3.12/3.13 on Windows, Linux and macOS.
- Core dependencies: NumPy, SciPy, jsonschema. Optional web: FastAPI, Uvicorn. Development: pytest, httpx, psutil.
- Bounded workers and subprocess timeouts; cancellation must terminate active processing without altering source media.
- Unique temporary directory per run, owner-aware cleanup restricted to that run, and `--keep-temp` for investigation. Standalone extraction must preserve WAVs for the next stage.
- Atomic JSON/XML writes where supported. Validate schema version and cross-artifact IDs before consuming data.
- Package JSON schemas and web static assets in source distributions and wheels. Keep runtime-only imports independent of FastAPI.

## Acceptance evidence

The complete local suite passed 145 tests plus 28 subtests. Browser QA confirmed rational FPS, correct partial status, accepted-match metrics, nine alignment rows, four orphan rows and five visible downloads. The recorded 13-file pipeline run aligned nine media in two groups, retained four orphans, and passed structural XML validation. The Windows installer succeeded against an existing venv without system provisioning. See the [validation report](validation-report.md).

The six CI matrix results, clean-machine/system provisioning checks and actual Premiere import still require evidence. The supplied XML is a structural fixture only; its offsets differ from acoustic results. A valid XML tree, synthetic benchmark or passing smoke test does not demonstrate Premiere compatibility or calibrated matching accuracy.
