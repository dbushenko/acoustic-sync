"""Module A: bounded FFmpeg extraction, producing a media-manifest JSON file."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from pathlib import Path
import time
import uuid
from acoustic_sync.config import Config
from acoustic_sync.contracts import VERSION, atomic_json, validate
from acoustic_sync.runtime import Cancellation, Cancelled, run_process
from acoustic_sync.storage import cleanup_owned, protect_output
from .probe import probe
from .scanner import scan

log = logging.getLogger("acoustic_sync.extraction")


def extract(input_dir: Path, manifest_path: Path, config: Config, cancel: Cancellation | None = None,
            progress=None, temp_dir: Path | None = None) -> dict:
    temporary = (temp_dir or Path.cwd() / "tmp_audio" / uuid.uuid4().hex).absolute()
    if temporary.exists() or any(p.is_symlink() or p.is_junction() for p in (temporary, *temporary.parents)):
        raise ValueError(f"Temporary run directory must be new and not traverse links: {temporary}")
    protect_output(manifest_path, [], suffix=".json", forbidden_roots=[temporary])
    try:
        return _extract(input_dir, manifest_path, config, cancel, progress, temporary)
    except BaseException:
        if not config.keep_temp:
            try:
                cleanup_owned(temporary, temporary.name, temporary.parent)
            except Exception as error:
                log.error("Cleanup after extraction failure: %s", error)
            if temporary.parent.name == "tmp_audio":
                try:
                    temporary.parent.rmdir()
                except OSError:
                    pass
        raise


def _extract(input_dir: Path, manifest_path: Path, config: Config, cancel: Cancellation | None = None,
             progress=None, temp_dir: Path | None = None) -> dict:
    cancel = cancel or Cancellation()
    temporary = (temp_dir or Path.cwd() / "tmp_audio" / uuid.uuid4().hex).resolve()
    temporary.mkdir(parents=True, exist_ok=False)
    atomic_json(temporary / ".owner.json", {"purpose": "acoustic-sync", "run_id": temporary.name})
    sources = scan(Path(input_dir), exclude=[temporary])
    if not sources:
        raise ValueError("No supported media files found")
    protect_output(manifest_path, [s["file_path"] for s in sources], suffix=".json", forbidden_roots=[temporary])
    start = time.monotonic()

    def process(item):
        cancel.check()
        try:
            media = probe(item, cancel, min(config.timeout, 120))
            for stream in media["audio_streams"]:
                cancel.check()
                wav = temporary / f"{item['id']}-{stream['index']}.wav"
                try:
                    run_process(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-threads", "1",
                                 "-i", item["file_path"], "-map", f"0:{stream['index']}", "-vn", "-sn", "-dn",
                                 "-ac", "1", "-ar", str(config.sample_rate), "-c:a", "pcm_s16le", "-threads", "1", str(wav)],
                                cancel, config.timeout)
                    media["references"].append({"id": f"{item['id']}:{stream['index']}", "stream_index": stream["index"],
                                                "wav_path": str(wav), "sample_rate": config.sample_rate,
                                                "origin_samples": round((float(stream["start_time"]) - float(media["origin_seconds"])) * config.sample_rate)})
                except (RuntimeError, TimeoutError) as error:
                    wav.unlink(missing_ok=True)
                    media["warnings"].append(f"Audio stream {stream['index']} extraction failed: {error}")
            if media["audio_streams"] and not media["references"]:
                media["status"] = "extraction_failed"
            return media
        except Cancelled:
            raise
        except (RuntimeError, ValueError, OSError, TimeoutError, KeyError) as error:
            return {**item, "kind": "audio" if Path(item["file_path"]).suffix.lower() in {".wav", ".mp3", ".flac", ".aac", ".m4a", ".aif", ".aiff", ".ogg", ".wma"} else "video",
                    "duration_seconds": 0, "duration": "0", "video": None, "audio_streams": [], "references": [],
                    "creation_time": None, "status": "error", "error": str(error), "warnings": []}

    result = []
    executor = ThreadPoolExecutor(max_workers=config.workers)
    futures = [executor.submit(process, item) for item in sources]
    try:
        for future in as_completed(futures):
            cancel.check()
            media = future.result()
            result.append(media)
            log.info("Extraction %d/%d %s [%s]", len(result), len(sources), media["relative_path"], media["status"])
            if progress:
                progress("extraction", len(result), len(sources), media["relative_path"])
    except BaseException:
        cancel.cancel()
        raise
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    cancel.check()
    manifest = {"schema_version": VERSION, "input_dir": str(Path(input_dir).resolve()), "sample_rate": config.sample_rate,
                "temp_dir": str(temporary), "media": sorted(result, key=lambda m: m["relative_path"]),
                "extraction_seconds": time.monotonic() - start, "config": config.to_dict()}
    validate(manifest, "media_manifest")
    atomic_json(manifest_path, manifest)
    return manifest
