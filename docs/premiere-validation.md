# Premiere validation

**Actual Adobe Premiere Pro import has not yet been tested.** Structural XML validation and automated tests cannot establish NLE behavior. Record the Premiere version, OS, source sample and observed results when this checklist is executed.

The supplied reference is `E:\Work\multicam-src\multicam.xml`, representing 13 source files. It is used for structure and source metadata only: its offsets differ from the acoustic results and are not timing ground truth. Private media is not bundled in the package or CI.

## Recorded sample evidence

`results/sample/sync_map.json` contains nine aligned media in two groups and four unmatched media. The completed pipeline artifact `results/sample/run_report.json` records all 13 media preserved, two groups, four orphans, no failed media, approximately 4.39 seconds elapsed, three video tracks and eight audio tracks, with structural validation passing. The status is `partial`, reflecting unresolved clips rather than failed extraction. This is an end-to-end local sample run; the 100-file benchmark in [development](development.md) measures matching only.

| Unmatched source | Recorded reason |
| --- | --- |
| `dji/DJI_20260807184930_0011_D.MP4` | `clock_drift_or_inconsistent_offset` |
| `dji/DJI_20260807185257_0012_D.MP4` | `clock_drift_or_inconsistent_offset` |
| `dji/DJI_20260807185602_0013_D.MP4` | `clock_drift_or_inconsistent_offset` |
| `r8/MVI_2029.MP4` | `no_acoustic_match` |

The first three sources are the August DJI clips. Their rejection reason does not prove clock drift; inconsistent acoustic estimates can produce the same flag. All original audio channels are exported enabled. The full local suite passed 145 tests plus 28 subtests, and browser QA confirmed the partial-result UI; see the [validation report](validation-report.md). Manual channel routing and acoustic alignment checks in Premiere remain unperformed.

## Prepare

1. Keep original media and reference XML unchanged. Generate a new output XML under a separate output directory using the same media folder and the desired sequence rate.
2. Save the generated manifest, sync map, logs and exporter validation report. Use `--keep-temp` if matching evidence needs inspection.
3. Confirm every readable source is accounted for, including media with no matching reference. Distinguish unreadable probe errors from playable `extraction_failed` media.

## Structural checks

- Root is `xmeml version="4"`, with sequence and source rates. A 25 fps rate is timebase 25 with `ntsc=FALSE`; 30000/1001 is timebase 30 with `ntsc=TRUE`.
- Source in/out/duration uses source rate; sequence start/end uses sequence rate. Frame rounding should not accumulate floating-point drift.
- IDs are unique, referenced files exist, file URLs handle spaces and non-ASCII names, links are reciprocal, channel indices match original streams, and source bounds stay within file durations.
- All original audio channels and clips are enabled. Matching WAVs must not replace originals. Overlapping sources occupy compatible separate tracks.
- Disconnected groups and orphans have explicit labels and two-second section gaps. Their layout must not imply a measured absolute offset.

## Import and inspect manually

1. Import into a new Premiere project, record warnings, and relink only if necessary. Confirm all 13 expected source files are represented or have a documented read failure; count distinct source paths rather than clipitems (audio channels create multiple clipitems).
2. Check sequence FPS, width and height, each source's duration, and mixed-rate material. Compare the supplied XML's source metadata where applicable.
3. Solo each original channel to verify correct stream/channel routing and enabled state. Check linked audio/video selection, not only audible mix output.
4. At several events near the beginning, middle and end of each group, compare visible action and audio transients. Record residual timing errors in frames or milliseconds.
5. Inspect `NOT_SYNCED` orphans interleaved by approximate recording date and `RELATIVE_TIMING_UNKNOWN` disconnected groups. Verify no readable silent or extraction-failed source disappeared.
6. Inspect flagged drift across the full clip. Confirm the export has not applied unintended speed changes, cuts or corrections.
7. Save/reopen the Premiere project and play across group boundaries. Optionally export a fresh FCP XML for a semantic round-trip comparison; byte equality is not expected.

## Result record

| Item | Result |
| --- | --- |
| Date, OS, Premiere version | Not run |
| CLI version / commit / command | Not run |
| Source files accounted for | Not run (reference expectation: 13) |
| Import warnings / offline media | Not run |
| Original audio streams enabled and mapped | Not run |
| Residual alignment at start/middle/end | Not run |
| Rational rates / source bounds / markers | Not run |
| Save/reopen and playback | Not run |

Only replace these statuses with observed evidence. Keep structural, synthetic, real-media and Premiere validation results separate.
