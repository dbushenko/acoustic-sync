# Architecture

FCP7 output uses a top-level `xmeml/sequence` and a sibling `Source media` bin. The export is XML only; no Premiere project file is created or referenced. Nested `bin/children` nodes reproduce media `relative_path` directories. Each readable source has one `clip` master with its original filename, explicit video/audio tracks, and shared file references; sequence `clipitem/masterclipid` references that master. Validation checks master and file references. Legacy XML with a top-level sequence remains accepted by the validator. Export does not access the source filesystem to construct bins.

The pipeline uses JSON boundaries so extraction, matching and export can be rerun independently. The CLI invokes the extraction, matching and export components through `pipeline.run`, or calls the stages individually.

```text
Original media -> scanner / ffprobe -> FFmpeg references -> media_manifest.json
                                                           |
                                      spectrogram hashes / SQLite index
                                                           |
                                      candidates -> local FFT verification
                                                           |
                                      strong-edge graph -> sync_map.json
                                                           |
                                      rational timeline -> xmeml v4
```

Extraction records all probed streams and produces one mono reference per audio stream. The manifest holds source metadata and temporary WAV paths. The matcher consumes those references, stores hash occurrences in SQLite, verifies candidate offsets, and returns independent groups plus unresolved clips. The exporter consumes embedded media metadata and samples in `sync_map`; original sources remain the timeline's media references.

`origin_samples` handles stream timestamps before graph placement. Group-local offsets are distinct from editorial placement: packing groups two seconds apart does not establish acoustic relationships between them. Export rounding occurs at the frame boundary using rational rates.

## Stage contracts

Config validates strict integer sample rates/workers, boolean keep-temp, confidence bounds, and finite positive numeric timeout/minimum overlap. Booleans cannot stand in for numeric options. Width/height, cancellation and verbosity are separate CLI controls. Contracts require actual JSON integers, valid timing values, complete playable-video metadata, unique IDs/groups, and references tied to a declared audio stream at the root reference rate. They recursively reject non-finite floating-point values in nested lists and objects before schema validation. JSON writers also reject NaN and infinity.

Schema, graph and exporter use confidence scores from 0 to 100. The timeline accepts `extraction_failed`, preserving probed metadata for playable sources whose matching references failed. Original audio channels, clips and tracks are exported enabled. All clip names retain their original filenames; unmatched section markers include `[NOT_SYNCED]`; disconnected-group markers include `[RELATIVE_TIMING_UNKNOWN]`.

See [matching](matching.md) for scoring and offset conventions, [development](development.md) for measured benchmark evidence, and [Premiere validation](premiere-validation.md) for sample results and manual acceptance criteria.

## Resource ownership

`run` owns `tmp_audio/<run_id>` under the working directory. Its `finally` block attempts reference cleanup on success, failure and cancellation unless `--keep-temp` is set. Shared cleanup lives in `storage.py` as `cleanup_owned`: it checks the run-directory name, resolved expected parent and exact ownership marker, and rejects symlinks/junctions in the target or its ancestors. Pipeline cleanup additionally requires the `tmp_audio` parent name. Cleanup errors are logged and added to `run_report.json`; a previously completed result becomes partial. The report also records timings, failed media and export details. An exclusive `.acoustic-sync.lock` protects the output directory during a run.

Standalone `extract` intentionally retains successful references for later `match`, even without `--keep-temp`. This includes a completed manifest containing individual `error` or `extraction_failed` records: other references may still be usable. An exception or cancellation invokes shared owned cleanup unless `--keep-temp` is set, including failures before manifest creation. Extraction checks cancellation again after workers finish and before constructing the manifest. A cleanup exception is logged without replacing the original extraction failure or cancellation. Invalid ownership or filesystem links cause cleanup to refuse removal. Preserve completed standalone references until matching is finished.

Output protection resolves destination paths before comparison and checks existing-file identity to catch aliases. Extraction requires a `.json` manifest outside its temporary reference directory and protects discovered source files. Matching requires a `.json` sync map and protects its input manifest, media and reference WAVs. XML export requires a `.xml` destination and protects source media. These checks reject input replacement before artifact writes; they do not grant arbitrary outputs permission to overwrite unrelated files.

The matcher owns a separate `fingerprints-*` temporary directory beside the manifest. Its processing `finally` closes SQLite and removes that index; `--keep-temp` does not retain the index. Original source files are not cleanup targets. Failure, cancellation, ownership and filesystem-link cases belong in the regression suite.

## Future work, not current claims

Clock-drift correction/resampling, calibrated confidence probabilities, absolute timing between disconnected groups, automatic creative multicam switching, and guaranteed Premiere version compatibility are outside the current implementation. The recorded 100-file matching benchmark does not establish long-recording or end-to-end scaling; clean-machine installer support also requires platform validation.

Track placement reserves one contiguous bank per input-relative source folder, separately for video and audio. Interval packing occurs within a folder only. Groups and orphan status do not change folder assignment. Export reports expose the resulting track-to-folder mapping in `track_folders`.
