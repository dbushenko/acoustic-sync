"""CLI entry; expensive dependencies are imported only by their stage."""
import argparse
import json
import logging
from pathlib import Path
import shutil
import signal
import sys
from acoustic_sync import __version__
from acoustic_sync.config import Config
from acoustic_sync.contracts import read_json
from acoustic_sync.logging_config import configure
from acoustic_sync.runtime import Cancellation, Cancelled, run_process


def _common(parser):
    parser.add_argument("--sample-rate", type=int, choices=(11025, 22050), default=22050)
    parser.add_argument("--confidence-threshold", type=float, default=70)
    parser.add_argument("--workers", type=int, default=Config().workers)
    parser.add_argument("--timeout", type=float, default=3600)
    parser.add_argument("--min-overlap", type=float, default=1)
    parser.add_argument("--keep-temp", action="store_true")
    parser.add_argument("--cancel-file", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--verbose", action="store_true")


def _export_options(parser):
    parser.add_argument("--output_xml", required=True, type=Path)
    parser.add_argument("--fps", default="25", help="25, 29.97, or exact rational such as 30000/1001")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)


def parser():
    root = argparse.ArgumentParser(prog="acoustic-sync", description="Acoustic fingerprint synchronization and FCP7 XML export")
    root.add_argument("--version", action="version", version=__version__)
    sub = root.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Run extraction, matching and export (default command)")
    run.add_argument("--input_dir", required=True, type=Path)
    _common(run)
    _export_options(run)
    extract = sub.add_parser("extract", help="Create reference WAVs and a JSON manifest")
    extract.add_argument("--input_dir", required=True, type=Path)
    extract.add_argument("--manifest", required=True, type=Path)
    _common(extract)
    match = sub.add_parser("match", help="Build a sync map from an extraction manifest")
    match.add_argument("--manifest", required=True, type=Path)
    match.add_argument("--sync_map", required=True, type=Path)
    match.add_argument("--fps", default="25", help="Project frame rate used as drift tolerance")
    _common(match)
    export = sub.add_parser("export", help="Generate XML from a self-contained sync map")
    export.add_argument("--sync_map", required=True, type=Path)
    _export_options(export)
    serve = sub.add_parser("serve", help="Start the optional localhost web UI")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--state-dir", type=Path)
    serve.add_argument("--open-browser", action="store_true", help="Open the UI when the server is ready")
    sub.add_parser("doctor", help="Check runtime and required executables")
    return root


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("--") and argv[0] not in ("--help", "--version"):
        argv.insert(0, "run")
    args = parser().parse_args(argv)
    cancel = Cancellation(getattr(args, "cancel_file", None))
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous[sig] = signal.signal(sig, lambda *_: cancel.cancel())
        except ValueError:
            pass  # Callable CLI may be hosted in a test thread.
    configure(verbose=getattr(args, "verbose", False))
    log = logging.getLogger("acoustic_sync.cli")
    try:
        if args.command == "doctor":
            import importlib.metadata
            result = {"python": sys.version.split()[0], "executable": sys.executable, "version": __version__, "tools": {}, "dependencies": {}}
            for tool in ("ffmpeg", "ffprobe"):
                executable = shutil.which(tool)
                result["tools"][tool] = {"path": executable, "version": run_process([executable, "-version"], cancel, 10).splitlines()[0] if executable else None}
            for package in ("numpy", "scipy", "jsonschema"):
                try:
                    result["dependencies"][package] = importlib.metadata.version(package)
                except importlib.metadata.PackageNotFoundError:
                    result["dependencies"][package] = None
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if all(v["path"] for v in result["tools"].values()) and all(result["dependencies"].values()) else 1
        if args.command == "serve":
            try:
                from acoustic_sync.web.server import run_server
                from acoustic_sync.web.app import create_app
            except ImportError:
                raise ValueError("Web dependencies missing. Install acoustic-sync[web] or requirements/web.txt.") from None
            if not 1 <= args.port <= 65535:
                raise ValueError("port must be 1..65535")
            # Restore Uvicorn signal ownership before starting its event loop.
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            run_server(create_app(args.state_dir), port=args.port, open_browser=args.open_browser)
            return 0
        from acoustic_sync.timeline.rates import parse_rate
        parse_rate(getattr(args, "fps", "25"))
        if args.command == "export":
            from acoustic_sync.timeline.fcp7 import export_xml
            summary = export_xml(read_json(args.sync_map, "sync_map"), args.output_xml, fps=args.fps, width=args.width, height=args.height)
            print(json.dumps(summary, indent=2))
            return 0
        config = Config(sample_rate=args.sample_rate, confidence_threshold=args.confidence_threshold,
                        workers=args.workers, timeout=args.timeout, fps=getattr(args, "fps", "25"),
                        keep_temp=args.keep_temp, min_overlap=args.min_overlap)
        if args.command in ("run", "extract") and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
            raise ValueError("FFmpeg and FFprobe must be available on PATH. Run acoustic-sync doctor.")
        if args.command == "run":
            from acoustic_sync.pipeline import run
            result = run(args.input_dir, args.output_xml, config, cancel, args.width, args.height)
            log.info("%s: %s (%.2fs)", result["status"], args.output_xml, result["elapsed_seconds"])
            return 2 if result["status"] == "partial" else 0
        if args.command == "extract":
            from acoustic_sync.extraction.preprocess import extract
            result = extract(args.input_dir, args.manifest, config, cancel)
            return 2 if any(m["status"] in ("error", "extraction_failed") for m in result["media"]) else 0
        if args.command == "match":
            from acoustic_sync.matching.engine import match
            result = match(args.manifest, args.sync_map, config, cancel)
            return 2 if result["unmatched_clips"] else 0
    except (Cancelled, KeyboardInterrupt):
        cancel.cancel()
        log.warning("Cancelled")
        return 130
    except Exception as error:
        log.error("%s", error, exc_info=getattr(args, "verbose", False))
        return 1
    finally:
        for sig, handler in previous.items():
            try:
                signal.signal(sig, handler)
            except ValueError:
                pass
    return 0
