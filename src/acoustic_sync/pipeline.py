"""Pipeline lifecycle: JSON stage boundaries, durable reports, owned cleanup."""
from dataclasses import asdict
import logging
from pathlib import Path
import time
import uuid
from acoustic_sync.config import Config
from acoustic_sync.contracts import atomic_json
from acoustic_sync.runtime import Cancellation, Cancelled
from acoustic_sync.storage import cleanup_owned

log = logging.getLogger("acoustic_sync.pipeline")


def cleanup_temp(path: Path, run_id: str):
    """Never remove another run or an arbitrary user directory."""
    path = path.absolute()
    if path.name != run_id or path.parent.name != "tmp_audio":
        raise ValueError(f"Refusing unsafe cleanup target: {path}")
    cleanup_owned(path, run_id, path.parent)
    try:
        path.parent.rmdir()  # Only remove the parent when it is empty.
    except OSError:
        pass


class OutputLock:
    def __init__(self, directory: Path):
        self.path = directory / ".acoustic-sync.lock"

    def __enter__(self):
        import os
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.handle = self.path.open("x", encoding="utf-8")
        except FileExistsError:
            raise ValueError(f"Output directory is locked by another run: {self.path}. If a process crashed, verify it stopped before removing this lock.") from None
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        return self

    def __exit__(self, *args):
        self.handle.close()
        self.path.unlink(missing_ok=True)


def run(input_dir: Path, output_xml: Path, config: Config, cancel: Cancellation | None = None,
        width: int | None = None, height: int | None = None) -> dict:
    from acoustic_sync.extraction.preprocess import extract
    from acoustic_sync.matching.engine import match
    from acoustic_sync.timeline.fcp7 import export_xml
    cancel = cancel or Cancellation()
    output_xml = Path(output_xml).resolve()
    directory = output_xml.parent
    if output_xml.suffix.lower() != ".xml":
        raise ValueError("output_xml must have an .xml extension")
    run_id = uuid.uuid4().hex
    temp = Path.cwd() / "tmp_audio" / run_id
    started = time.monotonic()
    report = {"run_id": run_id, "status": "running", "config": asdict(config), "warnings": [], "stages": {}}

    def progress(stage, completed, total, message):
        atomic_json(directory / "progress.json", {"stage": stage, "completed": completed, "total": total, "message": message})

    with OutputLock(directory):
        from acoustic_sync.logging_config import configure
        configure(directory / "run.log", logging.getLogger("acoustic_sync").level == logging.DEBUG)
        try:
            progress("extraction", 0, 0, "Scanning input directory")
            tick = time.monotonic()
            manifest = extract(input_dir, directory / "media_manifest.json", config, cancel, progress, temp)
            report["stages"]["extraction_seconds"] = time.monotonic()-tick
            if not any(m["status"] != "error" for m in manifest["media"]):
                raise ValueError("No readable media; inspect media_manifest.json for per-file errors")
            cancel.check()
            tick = time.monotonic()
            sync = match(directory / "media_manifest.json", directory / "sync_map.json", config, cancel, progress)
            report["stages"]["matching_seconds"] = time.monotonic()-tick
            cancel.check()
            progress("export", 0, 1, "Building FCP7 XML")
            tick = time.monotonic()
            exported = export_xml(sync, output_xml, fps=config.fps, width=width, height=height)
            report["stages"]["export_seconds"] = time.monotonic()-tick
            report["export"] = exported
            report["statistics"] = sync["statistics"]
            report["groups"] = len(sync["groups"])
            report["unmatched"] = len(sync["unmatched_clips"])
            report["warnings"] = sync["warnings"] + exported.get("warnings", []) + [f"{m['relative_path']}: {w}" for m in sync["media"] for w in m.get("warnings", [])]
            report["failed_media"] = [{"file_path": m["file_path"], "error": m.get("error", m["status"])} for m in sync["media"] if m["status"] in ("error", "extraction_failed")]
            report["status"] = "partial" if report["unmatched"] or report["failed_media"] or report["warnings"] else "completed"
            progress(report["status"], 1, 1, "Timeline exported")
        except Cancelled:
            report["status"] = "cancelled"
            progress("cancelled", 0, 0, "Operation cancelled")
            raise
        except BaseException as error:
            report["status"] = "failed"
            report["error"] = str(error)
            progress("failed", 0, 0, str(error))
            raise
        finally:
            if not config.keep_temp:
                try:
                    cleanup_temp(temp, run_id)
                except Exception as error:
                    log.error("Temporary cleanup failed: %s", error)
                    report["warnings"].append(f"Temporary cleanup failed: {error}")
                    if report["status"] == "completed":
                        report["status"] = "partial"
            report["elapsed_seconds"] = time.monotonic()-started
            atomic_json(directory / "run_report.json", report)
    return report
