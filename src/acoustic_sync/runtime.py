"""Cooperative cancellation and subprocess ownership (no shell invocation)."""
import json
from pathlib import Path
import subprocess
import threading
import time


class Cancelled(Exception):
    """User cancelled a pipeline operation."""


class Cancellation:
    def __init__(self, path: Path | None = None):
        self.event = threading.Event()
        self.path = Path(path) if path else None

    def cancel(self):
        self.event.set()

    def check(self):
        if self.event.is_set() or (self.path and self.path.exists()):
            raise Cancelled("Operation cancelled")


def run_process(args: list[str], cancel: Cancellation, timeout: float) -> str:
    cancel.check()
    flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8", errors="replace", creationflags=flags)
    start = time.monotonic()
    try:
        while True:
            cancel.check()
            if time.monotonic() - start > timeout:
                raise TimeoutError(f"{Path(args[0]).name} exceeded {timeout:g}s")
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode:
            raise RuntimeError(f"{Path(args[0]).name} failed ({process.returncode}): {stderr[-4000:]}")
        return stdout
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def probe_json(path: Path, cancel: Cancellation, timeout: float) -> dict:
    return json.loads(run_process(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], cancel, timeout))
