# Matching design and interpretation

This describes the `matching/*.py` implementation. See [development](development.md) for measured performance and [Premiere validation](premiere-validation.md) for sample evidence. Source inspection is separate from test execution.

## Candidate search

1. Read per-stream PCM16 mono matching references at a consistent sample rate (22050 Hz by default).
2. Compute spectrograms in 20-second core chunks with three seconds of context. At 22050 Hz, the FFT size is 2048 and hop is 128 (1024/64 at 11025 Hz). Select up to four peaks per 0.1-second bucket and pair each anchor with up to eight subsequent peaks 0.08-2 seconds away. Hash the quantized frequencies and time difference.
3. Store hash occurrences in SQLite with `origin_samples` already added to anchor times. The inverted-index join compares different media only and ignores hashes with more than 100 postings. Vote in approximately 23.22 ms offset bins, retain at most 24 bins per reference pair, and select up to three modes separated by at least 150 ms.
4. Recount distinct supporting anchors within two bins of each mode to handle quantization boundaries. Select up to 15 anchor positions distributed across that support span for local verification. No full all-pair correlation is performed.
5. Verify shortlisted modes, score the evidence, and check accepted offsets across audio streams. If accepted hypotheses for a media pair disagree by more than one project frame after their direction is normalized, reject them as `ambiguous_stream_or_repeated_content_offsets`.

Hash indexing avoids mandatory full correlation of every pair, but common hashes and noisy/repetitive recordings can still be expensive. Bounded candidates, windows, workers and timeouts need measured stress tests. No universal speed or memory bound is claimed.

## Local FFT verification

`refinement.py` centers windows on the selected fingerprint landmarks, clips their positions to the overlapping region, and deduplicates coincident positions. Without landmarks it falls back to seven evenly spaced positions. Each window is nominally 0.5 seconds, shortened when overlap requires it; windows shorter than 0.25 seconds are rejected. The search radius is +/-0.12 seconds around the candidate offset.

Both signals receive pre-emphasis `y[n] = x[n] - 0.95*x[n-1]`. The verifier searches one reference around a fixed window from the other using FFT correlation, normalized by local signal energy. It uses the absolute peak, allowing polarity inversion. A usable peak must score at least 0.10 and lie away from the search boundary. At least three usable windows are required; otherwise the result is `weak_local_verification`.

A stationary consensus can exclude isolated false peaks only when at least `max(3, ceil(0.75*N))` of the N usable estimates lie within a radius of `max(2 samples, round(sample_rate * min(0.005 seconds, frame_seconds/4)))` around one estimate. Without that 75% consensus, all estimates remain. The retained median gives the refined offset; raw offsets remain in `raw_window_offsets_samples`, while `window_offsets_samples` contains retained estimates. Three windows need not be independent if their positions are close; coverage is reported separately.

Retained max-minus-min spread greater than one project frame produces `clock_drift_or_inconsistent_offset` and prevents acceptance. `verification_coverage` is the retained position span plus one window divided by candidate overlap, capped at 1. A fitted slope is reported as `drift_ppm`; it is diagnostic, not proof of clock drift. No correction is applied, and this gate is not a guarantee of detecting every drift pattern.

## Confidence and gates

Default acceptance requires verified local evidence and a heuristic score of at least 70 out of 100. `confidence.py` stores these components in `evidence.score_components`:

| Component | Points |
| --- | --- |
| Landmarks | `25 * min(1, support / 20)` |
| Coverage | `20 * min(1, max(span_seconds / max(0.1, overlap_seconds), verification_coverage) * 1.25)` |
| Correlation | `25 * min(1, median_correlation / 0.25)` |
| Consistency | `15 * exp(-offset_spread_seconds / 0.015)` |
| Uniqueness | `15 * max(0, 1 - alternative_support / max(1, support))` |

The sum is capped at 100 and rounded to two decimals. An unverified refinement scores zero. Fewer than eight supporting anchors, landmark span below `min(0.7 seconds, min_overlap)`, or overlap shorter than `min_overlap` caps the score at 49 and returns `insufficient_evidence`. Alternative-mode support at least 80% of the selected mode caps it at 49 with `ambiguous_repeated_content`. A verified score below the configured threshold is `below_confidence_threshold`. These gates remain in effect even when the threshold is lowered. Silence and repetitive tones can produce misleading correlation; one large peak is insufficient.

The score is not a calibrated probability or a percentage of correctly synchronized clips. Lowering `--confidence-threshold` increases acceptance of weak evidence and should trigger manual review. `--min-overlap` controls a minimum overlap requirement, not an assertion that every short match is reliable. The engine records evaluated candidates and their evidence in `matches`, including rejected candidates.

## Groups, cycles and drift

An edge `a -> b` stores `start(b) - start(a)` in manifest-rate samples: positive means b starts later. Its reverse has the opposite sign. Index times already include stream origins; refinement accounts for those origins when reading WAV positions, so do not apply the origin correction again to the final media offset.

Accepted matches are processed in descending confidence order. An edge joining previously disconnected vertices is added; an edge closing a path is checked against that path's summed offset. A residual greater than one project frame rejects it as `inconsistent_graph_cycle`. A consistent closing edge stays accepted in the match diagnostics but is not added to the adjacency structure. The retained graph therefore provides a spanning forest, not a least-squares timing adjustment.

Within a component, reference selection prefers audio-only media, then higher retained graph degree, longer duration, and relative path as a deterministic tie-breaker. Path confidence is the weakest edge score; the reference's self-path scores 100. `aligned_clips.offset_samples` is signed `start(file) - start(reference)`. Group member offsets subtract the minimum of these signed offsets, making the earliest member zero. For example, relative offsets -22050, 0 and 44100 at 22050 Hz become group offsets 0, 22050 and 66150. Reference selection does not establish a global wall clock. Singletons go to `unmatched_clips`.

Each group records `relative_timing_known: false`: relationships to other groups are unknown. Drift/inconsistency remains in match evidence for manual review without time stretching or inventing absolute time. The exporter packs sections with a two-second gap, labels disconnected-group markers `[RELATIVE_TIMING_UNKNOWN]`, and labels orphan section markers `[NOT_SYNCED]`. Clip names retain their original filenames. All original audio channels are enabled.

## Validation scenarios

Cover known positive/negative offsets, stream timestamp shifts, different sample rates, gain/noise changes, silence, periodic signals, minimal overlap, long clips, disconnected groups, inconsistent cycles, clock drift, no-audio video, and failed reference extraction. Check both accepted offsets and rejection behavior. See [development](development.md) for the CI scope.

The saved sample sync map contains nine aligned media in two groups and four unmatched media. The matching-only benchmark records 100 eight-second sources, 20 groups and zero unmatched sources. The full local suite passed 145 tests plus 28 subtests; see the [validation report](validation-report.md). These results do not establish Premiere acceptance or calibrated real-world accuracy.
