# JSON contracts

The authoritative runtime schemas are packaged at `src/acoustic_sync/schemas/media_manifest.json` and `sync_map.json` and loaded through `importlib.resources`. Both use `schema_version: "1.0"`. Do not substitute a field named `version`. Application validation extends Draft 2020-12 with strict integer types and checks timing, metadata, IDs and reference relationships. Running an ordinary external schema validator alone does not reproduce all application checks.

Integer fields require actual JSON integers: `1` is accepted where otherwise valid, while `1.0`, `true` and `"1"` are not interchangeable. This applies to schema integer fields, root/reference sample rates, and video index/dimensions. Config likewise requires integer sample rate/workers, a boolean keep-temp value, and non-boolean numeric timeout, minimum overlap and confidence.

## media_manifest

Required top-level fields: `schema_version`, `sample_rate`, `media`, `input_dir`, `temp_dir`. `sample_rate` is 22050 by default or 11025. Every offset in reference samples uses this rate, not the original stream rate.

Each `media` item requires:

| Field | Meaning |
| --- | --- |
| `id` | Unique, nonempty media identifier. |
| `file_path`, `relative_path` | Original source path and input-relative path. |
| `kind` | `video` or `audio`. |
| `duration_seconds`, `duration` | Nonnegative numeric seconds and a string duration representation for rational timing. |
| `video` | Video metadata object or null. Export needs frame rate, width, height and stream timing. |
| `audio_streams` | Original stream metadata: `index`, `channels`, `sample_rate`, `start_time`, `duration`; exporter also consumes bit depth. |
| `status` | `ready`, `no_audio`, `extraction_failed`, or `error`. |

Each `references` entry requires `id`, `wav_path`, `sample_rate`, `origin_samples`, and **`stream_index`**. That index must identify a declared audio stream in the same media record. The reference sample rate must equal the root manifest/sync-map sample rate, not necessarily the original stream's rate. Audio stream indices and reference IDs must each be unique within a media item. These are matching references, not export audio. `origin_samples = round((stream_start_time - media_origin_seconds) * sample_rate)`, relative to primary video or the first audio origin if video is absent. It may be negative. The origin must be included when translating a correlation offset back to a source-media offset.

Media `duration` must parse as a finite nonnegative rational number string. Audio stream duration must be positive, and start time must parse as a finite rational value. Every non-error video record requires `video.index`, `width`, `height`, `frame_rate`, `duration`, and `start_time`. Index is a nonnegative integer; dimensions are positive integers; video frame rate and duration must be positive and timing values must parse as finite rational values. Examples include duration `"12.5"`, rate `"30000/1001"`, and signed start time `"-0.04"`; malformed, NaN/infinite and zero-denominator timing values are rejected.

`extraction_failed` means a probed media item has audio but no usable reference extraction; the source may still be playable and must be retained for export. Partial stream failure can leave a usable `ready` item with warnings and fewer references. `no_audio` keeps silent video. `error` records unreadable/unprobeable input and diagnostics.

Other emitted fields may include `config`, `extraction_seconds`, `warnings`, `error`, `origin_seconds`, and `creation_time`. Creation timestamps do not independently prove synchronization.

## sync_map

Required top-level fields: `schema_version`, `sample_rate`, `media`, `groups`, `matches`, `master_tracks`, `aligned_clips`, `unmatched_clips`. Embedded `media` uses the same record structure, allowing export without reopening the manifest or reading extracted WAVs.

Each group requires `id`, `reference_id`, and at least two `members`. Each member contains `media_id`, integer `offset_samples >= 0`, and `confidence` on the schema's **0-100** scale. Offsets are normalized within the group, with the earliest media origin at zero; `reference_id` must identify a member but need not be the earliest member. Confidence is a heuristic score. Do not confuse normalization of offsets with a 0-1 confidence scale.

`matches` contains `a_id`, `b_id`, original stream indices `a_stream`/`b_stream`, `offset_samples`, `offset_seconds`, `confidence`, `accepted`, `reason`, and `evidence`. The offset convention is **start(b) - start(a)**; a positive offset means b starts later. Evidence includes candidate support, alternative support, local verification windows, score components and drift diagnostics. Graph processing can change acceptance/reason and add `cycle_residual_samples`.

`master_tracks` currently contains **source file-path strings**, one per group's selected reference, not media IDs. `groups[].reference_id` and `aligned_clips[].matched_to_id` provide the reference IDs.

`aligned_clips` records `media_id`, `file_path`, `matched_to` (reference path), `matched_to_id`, signed `offset_samples` and `offset_seconds`, `confidence`, `group_id`, `indirect`, and `alignment_path`. Its offset is **start(file) - start(reference)** and may be negative. Group member offsets are a separate normalized representation: subtract the earliest signed offset in that group. Path confidence is the minimum edge score, with 100 for the reference itself. Groups also emit `relative_timing_known: false` for unknown inter-group timing.

`unmatched_clips` entries require `media_id`, `file_path`, `confidence`, and `reason`. Detailed evidence keys remain extensible; consumers should tolerate additive keys. The engine additionally emits `config`, `warnings`, and `statistics` (fingerprints, reference streams, matching seconds and accepted match count).

Media IDs and group IDs must be unique. Each group's reference must be one of its members. Every media ID must appear exactly once across group memberships and `unmatched_clips`; unknown, repeated and missing assignments are rejected. Do not silently drop unreadable entries from the JSON accounting: the exporter can explicitly report why it cannot create a playable clip. `aligned_clips` and `matches` are diagnostic/derived views rather than additional source occurrences.

Minimal empty documents (valid shape, not useful media jobs):

```json
{"schema_version":"1.0","sample_rate":22050,"input_dir":"/media","temp_dir":"/tmp/run-id","media":[]}
```

```json
{"schema_version":"1.0","sample_rate":22050,"media":[],"groups":[],"matches":[],"master_tracks":[],"aligned_clips":[],"unmatched_clips":[]}
```

Artifacts use UTF-8 JSON with finite numbers. Validation recursively checks floating-point values in nested objects and lists before schema validation, rejecting NaN and infinity even inside extensible evidence fields. Atomic writers use `allow_nan=False`. Config requires timeout and minimum overlap to be finite and positive. Preserve original paths and sample precision when editing artifacts. Unknown schema versions fail clearly. For Windows JSON strings, escape backslashes or use forward slashes. Temporary references are local paths and are not portable attachments.
