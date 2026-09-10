# Usage

Use the venv's `acoustic-sync` executable, or activate the venv first. Commands below omit the platform-specific executable path. `acoustic-sync --help` and each subcommand's `--help` describe the implemented parser.

## End-to-end

```powershell
acoustic-sync run --input_dir 'E:\Work\multicam-src' --output_xml '.\output\synced.xml' --fps 25 --confidence-threshold 70 --workers 4
# Omitting run selects the same default workflow:
acoustic-sync --input_dir 'E:\Work\multicam-src' --output_xml '.\output\synced.xml' --fps 25 --keep-temp
```

Use an output directory outside the source tree where possible. Source media stays in place and the XML references it; moving it later requires relinking in Premiere. The input is the media folder, not the sample XML. `multicam.xml` is a comparison artifact, not a source of acoustic offsets.

Manifest and sync-map outputs require `.json`; timeline outputs require `.xml` (case-insensitive). Destinations are checked using resolved paths and existing-file identity, so a symlink or hard-link alias cannot bypass protected-input comparisons. Extraction also rejects a manifest inside its temporary reference directory. Choose distinct output paths rather than reusing the input manifest, source media or reference WAVs.

## Staged workflow

```bash
acoustic-sync extract --input_dir /path/to/media --manifest output/media_manifest.json
acoustic-sync match --manifest output/media_manifest.json --sync_map output/sync_map.json
acoustic-sync export --sync_map output/sync_map.json --output_xml output/synced.xml --fps 25
```

Standalone extraction retains the WAV directory named by `media_manifest.temp_dir`, even without `--keep-temp`, so later matching can read it. Export uses embedded source metadata and does not require temporary WAVs. Matching uses the manifest's sample rate; changing `match --sample-rate` does not reinterpret existing samples. Re-extract to change the reference rate.

For end-to-end `run`, owned reference cleanup runs in `finally` on success, failure or cancellation unless `--keep-temp` is set; cleanup failures are recorded in `run_report.json`. Standalone extraction also cleans its owned directory on an exception or cancellation unless `--keep-temp` is set. A completed manifest with individual failed media retains its usable references for matching. The matcher's separate SQLite index is removed after processing even with `--keep-temp`. Cleanup refuses invalid ownership or linked filesystem paths. Do not manually delete another active job's directory.

Extraction checks late cancellation after workers finish and before producing the manifest. If cleanup itself fails during error handling, it logs that failure and preserves the original extraction exception/cancellation for the caller.

## Options

| Option | Purpose |
| --- | --- |
| `--input_dir` | Input media directory for `run` / `extract`. |
| `--output_xml` | Destination timeline for `run` / `export`. |
| `--manifest` | Manifest output for `extract`, input for `match`. |
| `--sync_map` | Sync-map output for `match`, input for `export`. |
| `--fps` | Sequence rate, default `25`; rational values such as `30000/1001` retain NTSC timing. |
| `--confidence-threshold` | Acceptance score, default `70` on 0-100; evidence gates still apply. |
| `--workers` | Bounded concurrency, 1-64; config defaults to min(4, CPU count). |
| `--keep-temp` | Retain end-to-end run references; standalone extraction already retains them. Does not retain the matcher's disposable index. |
| `--sample-rate` | Matching reference rate: 22050 default, or 11025. |
| `--timeout` | Positive processing timeout in seconds; config default 3600. |
| `--min-overlap` | Positive minimum verification overlap in seconds; config default 1.0. |
| `--width`, `--height` | Export sequence dimensions; do not change source media. |
| `--cancel-file` | Cooperative cancellation signal path; creating the file requests cancellation. Use a fresh absent path per run and see final command help for scope. |
| `--verbose` | More diagnostic logging. |
| `--port` | Port for `serve`; CLI and launcher default is 8765. |

Only supply options supported by the relevant subcommand. Width/height and FPS describe the export sequence; they do not resample audio or correct drift.

Processing options apply to `run`, `extract`, and `match`; `export` accepts only its sync map, output, FPS and dimension options. `match --fps` supplies the frame-based drift tolerance. `serve --state-dir` optionally selects a web job-state directory. The internal `--cancel-file` option is accepted by processing commands but hidden from help.

`Config` stores sample rate, confidence threshold, workers, timeout, FPS, keep-temp and minimum overlap. Width/height, cancellation-file path and verbosity are separate CLI controls. Worker count bounds extraction concurrency; it does not promise parallel FFT matching. The configured timeout is used for FFmpeg subprocesses, with probing capped at 120 seconds; it is not currently a wall-clock limit on the entire matching stage.

Exit codes: 0 for success, 1 for runtime failure, 2 for partial results/unmatched clips (also argparse usage errors), and 130 for cancellation. Review artifacts and logs when code 2 is returned; do not assume that no output was written. The web job runner maps pipeline exit 2 to `partial` and exit 130 to `cancelled`. Partial exports remain available for review.

## Doctor and web

```bash
acoustic-sync doctor
acoustic-sync serve --port 8765
```

Install the web profile first. The server uses localhost; paths entered in the web UI refer to the server's filesystem. Keep the server process running during jobs. The launchers `scripts/run-web.ps1 -Port 8765` and `bash scripts/run-web.sh 8765` use the checkout's venv without activation.

Both launchers default to port 8765 when the port is omitted. To isolate job state in a project-local directory:

```powershell
.\scripts\run-web.ps1 -StateDir '.\output\web-state'
```

```bash
bash scripts/run-web.sh --state-dir ./output/web-state
```

Paths with spaces must be quoted. These options forward directly to `serve --state-dir`; relative state paths resolve from the project root in both launchers. Launchers open the default browser after startup; use `-NoBrowser` (PowerShell) or `--no-browser` (Bash) to disable this.

Click **Browse** beside the source folder to navigate Home, drives, and folders, then click **Use folder**. For the output, browse to an existing destination folder, enter an XML filename (or select an existing XML), and confirm the selection. Selecting a destination does not write anything until you start the job. Paths can still be pasted directly. Choosing a source folder (or committing a typed source path) fills the output with `<source>/timeline.xml`; you can then change the output manually. The picker lists local folders without uploading your media.

Select a common frame rate from the dropdown, or choose **Custom** to type an exact rate or fraction such as `30000/1001`. NTSC presets use exact rational rates internally. All form settings (source and output paths, preset or Custom FPS, confidence threshold, and workers) are saved as you edit and restored from browser local storage across sessions on the same browser profile and server address/port. A manually chosen output is restored unchanged. Clearing browser storage resets these preferences; blocked storage does not prevent using the form. The UI displays confidence on the 0-100 scale. Its match metric counts accepted matches. Alignment rows show each file, reference, signed offset, group and confidence; a separate orphan table shows recordings needing review. A partial job displays completed export progress with a review notice rather than a runtime-failure message.

## Review results

Each source folder has its own fixed bank of video and audio tracks. Audio from video sources comes first, followed by standalone audio recordings; within each category, banks are ordered by relative folder path. Mixed folders receive separate camera-audio and standalone-audio banks. Clips from different folders never share a track, even when they do not overlap. Unmatched clips use the same folder bank as synchronized clips. Extra adjacent tracks are used for overlaps and simultaneous audio channels within the folder. Nested folders remain distinct; files at the input root use the root bank. The report includes `track_folders`; `orphan_video_tracks` and `orphan_audio_tracks` count tracks containing unmatched clips, not additional dedicated tracks.

Groups and unmatched recordings are interleaved by approximate recording date. A group uses its earliest known member timestamp and stays intact. Metadata full timestamps take priority, then full dates/times parsed from filenames, then date-only hints (midnight). Undated sections go last, ordered deterministically by relative path. Equal dates put synchronized groups first. Acoustic offsets remain unchanged, and sections still have two-second editorial gaps rather than real calendar gaps.

Supported filename examples: `DJI_20260910071433_0014_D.MP4`, `260910-071351.WAV` (2000–2099), `2026-09-10_07-14-33.mov`, and `20260910.mov`. Numeric clip counters such as `MVI_2030` are not dates. Metadata includes container/main-video/audio creation tags, QuickTime creation dates and BWF origination date/time. Invalid dates are ignored. Timezone-aware dates are compared in UTC; dates without a timezone are treated as UTC for deterministic approximate ordering, which cannot correct mis-set camera clocks. Modification time on disk is not used.

Export report markers contain `recording_time` with value, source, precision, timezone assumption and media ID; XML markers include the date hint. Re-export an existing sync map to use filename hints without re-analysis. Re-extraction is needed to collect newly supported metadata tags that an older manifest did not retain.

The XML contains one top-level sequence and a **Source media** bin, without a Premiere project file. Nested bins mirror folders relative to the selected input directory, for both video and audio. Files directly in that directory appear directly in Source media. Original clip names and disk paths stay intact; each timeline item references its corresponding master clip. This organizes newly imported media; it does not merge it with existing Premiere project items. Re-export an existing sync map to obtain this layout without repeating acoustic matching. Check the bin structure after import in your Premiere version.

Inspect warnings, match evidence and group membership before editing. A high score does not establish timing between disconnected groups. `RELATIVE_TIMING_UNKNOWN` means the two-second gap is editorial packing only. `NOT_SYNCED` means the original clip is retained without a trusted alignment. Flagged drift requires a manual review; no speed change is applied automatically. Follow [Premiere validation](premiere-validation.md) before relying on a generated sequence.
