"""Module B public entry: a manifest JSON in, self-contained sync-map JSON out."""
from fractions import Fraction
import logging
from pathlib import Path
import sqlite3
import tempfile
import time
from acoustic_sync.config import Config
from acoustic_sync.contracts import VERSION, atomic_json, read_json, validate
from acoustic_sync.runtime import Cancellation, Cancelled
from acoustic_sync.storage import protect_output
from .alignment_graph import align
from .candidates import candidates
from .confidence import confidence
from .fingerprints import fingerprint_chunks
from .index import FingerprintIndex
from .refinement import refine

log = logging.getLogger("acoustic_sync.matching")


def match(manifest_path: Path, sync_map_path: Path, config: Config, cancel: Cancellation | None = None, progress=None) -> dict:
    cancel = cancel or Cancellation()
    manifest = read_json(manifest_path, "media_manifest")
    sample_rate = manifest["sample_rate"]
    started = time.monotonic()
    media = manifest["media"]
    protect_output(sync_map_path, [manifest_path] + [m["file_path"] for m in media] +
                   [r["wav_path"] for m in media for r in m.get("references", [])], suffix=".json")
    references = []
    warnings = []
    for source in media:
        path = Path(source["file_path"])
        if source["status"] != "error":
            if not path.exists():
                raise ValueError(f"Source removed since extraction: {path}")
            stat = path.stat()
            if stat.st_size != source.get("size", stat.st_size) or stat.st_mtime_ns != source.get("mtime_ns", stat.st_mtime_ns):
                raise ValueError(f"Source changed since extraction; run extract again: {path}")
        for ref in source.get("references", []):
            if not Path(ref["wav_path"]).is_file():
                raise ValueError(f"Reference WAV missing; rerun extract: {ref['wav_path']}")
            references.append({**ref, "media_id": source["id"], "file_path": source["file_path"]})
    temporary = tempfile.TemporaryDirectory(prefix="fingerprints-", dir=Path(manifest_path).resolve().parent)
    index = FingerprintIndex(Path(temporary.name) / "index.sqlite")
    index.connection.set_progress_handler(lambda: 1 if cancel.event.is_set() or (cancel.path and cancel.path.exists()) else 0, 10000)
    total_hashes = 0
    matches = []
    aliases = {"29.97": "30000/1001", "23.976": "24000/1001", "59.94": "60000/1001"}
    frame_seconds = 1 / float(Fraction(aliases.get(config.fps, config.fps)))
    try:
        for stream_id, ref in enumerate(references):
            cancel.check()
            index.add_stream(stream_id, ref["media_id"])
            count = 0
            tick = time.monotonic()
            for rows in fingerprint_chunks(ref["wav_path"], sample_rate, cancel):
                index.add(stream_id, rows, ref["origin_samples"])
                count += len(rows)
            total_hashes += count
            log.info("Fingerprint %d/%d %s: %d hashes, %.0f hashes/s", stream_id+1, len(references),
                     Path(ref["file_path"]).name, count, count/max(0.001,time.monotonic()-tick))
            if progress:
                progress("fingerprinting", stream_id+1, len(references), Path(ref["file_path"]).name)
        index.finalize()
        for stream_id, ref in enumerate(references):
            cancel.check()
            hypotheses = candidates(index, stream_id, sample_rate, cancel)
            log.info("Matching %d/%d: %d fingerprint hypotheses", stream_id+1, len(references), len(hypotheses))
            for candidate in hypotheses:
                cancel.check()
                other = references[candidate["b_stream"]]
                evidence = refine(candidate, ref, other, sample_rate, cancel, frame_seconds)
                score, reason = confidence(candidate, evidence, config.min_overlap)
                accepted = reason == "verified" and score >= config.confidence_threshold
                if reason == "verified" and not accepted:
                    reason = "below_confidence_threshold"
                record = {"a_id": ref["media_id"], "b_id": other["media_id"],
                          "a_stream": ref["stream_index"], "b_stream": other["stream_index"],
                          "offset_samples": evidence.get("offset_samples", candidate["offset_samples"]),
                          "confidence": score, "accepted": accepted, "reason": reason,
                          "evidence": {**candidate, **evidence}}
                record["offset_seconds"] = record["offset_samples"]/sample_rate
                matches.append(record)
                log.info("Match %s -> %s offset=%+.6fs confidence=%.2f %s", Path(ref["file_path"]).name,
                         Path(other["file_path"]).name, record["offset_seconds"], score, reason)
            if progress:
                progress("matching", stream_id+1, len(references), Path(ref["file_path"]).name)
        # Multiple audio streams must agree before a media-level placement is trusted.
        pair_groups = {}
        for record in matches:
            if record["accepted"]:
                pair = tuple(sorted((record["a_id"], record["b_id"])))
                signed = record["offset_samples"] if record["a_id"] == pair[0] else -record["offset_samples"]
                pair_groups.setdefault(pair, []).append((record, signed))
        for values in pair_groups.values():
            if max(d for _, d in values)-min(d for _, d in values) > frame_seconds*sample_rate:
                for record, _ in values:
                    record["accepted"] = False
                    record["reason"] = "ambiguous_stream_or_repeated_content_offsets"
        groups, aligned, unmatched, masters = align(media, matches, sample_rate, frame_seconds)
        sync = {"schema_version": VERSION, "sample_rate": sample_rate, "media": media, "matches": matches,
                "groups": groups, "master_tracks": masters, "aligned_clips": aligned, "unmatched_clips": unmatched,
                "warnings": warnings, "config": config.to_dict(), "statistics": {"fingerprints": total_hashes,
                "reference_streams": len(references), "matching_seconds": time.monotonic()-started,
                "accepted_matches": sum(m["accepted"] for m in matches)}}
        cancel.check()
        validate(sync, "sync_map")
        atomic_json(sync_map_path, sync)
        return sync
    except sqlite3.OperationalError:
        cancel.check()
        raise
    finally:
        index.close()
        temporary.cleanup()
