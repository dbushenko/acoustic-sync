"""Persistent, bounded FIFO with exactly one pipeline subprocess."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid

TERMINAL = {"completed", "partial", "failed", "cancelled", "interrupted"}
ARTIFACTS = {"timeline.xml", "run_report.json", "media_manifest.json", "sync_map.json", "run.log"}


def read_json(path: Path):
    try:
        if path.stat().st_size > 8_000_000:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def terminate_tree(process):
    """Last-resort cancellation targets only the job's owned process tree."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=5, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.kill()
        process.wait(timeout=2)


class JobManager:
    def __init__(self, root: Path, capacity=8, cancel_grace=8.0):
        self.root = root.resolve()
        self.capacity = capacity
        self.cancel_grace = cancel_grace
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.jobs = {}
        self.thread = None
        self.process = None

    def directory(self, job):
        return self.root / job["id"]

    def save(self, job):
        directory = self.directory(job)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "status.tmp"
        temporary.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        temporary.replace(directory / "status.json")

    def start(self):
        self.root.mkdir(parents=True, exist_ok=True)
        self.stopping.clear()
        with self.lock:
            for path in self.root.glob("*/status.json"):
                job = read_json(path)
                if not isinstance(job, dict) or job.get("id") != path.parent.name:
                    continue
                if not all(key in job for key in ("status", "created_at", "output_xml", "input_dir")):
                    continue
                if job["status"] not in TERMINAL:
                    job.update(status="interrupted", finished_at=time.time(), error="Server restarted; submit again to resume work.")
                    self.save(job)
                self.jobs[job["id"]] = job
        self.thread = threading.Thread(target=self._schedule, name="acoustic-sync-jobs", daemon=True)
        self.thread.start()

    def stop(self):
        with self.lock:
            self.stopping.set()
            for job in self.jobs.values():
                if job["status"] not in TERMINAL:
                    self._signal_cancel(job)
                    job.update(status="interrupted", finished_at=time.time(), error="Server shut down; submit again to resume work.")
                    self.save(job)
        self.wake.set()
        if self.thread:
            self.thread.join()

    def submit(self, values):
        with self.lock:
            if self.stopping.is_set():
                raise RuntimeError("Server is shutting down")
            pending = [j for j in self.jobs.values() if j["status"] not in TERMINAL]
            folder = os.path.normcase(str(Path(values["output_xml"]).parent.resolve()))
            if any(os.path.normcase(str(Path(j["output_xml"]).parent.resolve())) == folder for j in pending):
                raise FileExistsError("Another queued or active job uses this output folder")
            if len(pending) >= self.capacity:
                raise OverflowError("Queue is full; wait for a job to finish")
            job = dict(values, id=uuid.uuid4().hex, status="queued", created_at=time.time(), started_at=None,
                       finished_at=None, error=None, returncode=None, artifacts=[])
            self.save(job)
            self.jobs[job["id"]] = job
        self.wake.set()
        return self.snapshot(job["id"])

    def _signal_cancel(self, job):
        (self.directory(job) / "cancel").touch()
        job.setdefault("cancel_requested_at", time.time())

    def cancel(self, identifier):
        with self.lock:
            job = self.jobs[identifier]
            if job["status"] not in TERMINAL:
                self._signal_cancel(job)
                if job["status"] == "queued":
                    job.update(status="cancelled", finished_at=time.time())
                else:
                    job["status"] = "cancelling"
                self.save(job)
        self.wake.set()
        return self.snapshot(identifier)

    def snapshot(self, identifier):
        with self.lock:
            job = dict(self.jobs[identifier])
            directory = self.directory(job)
            progress = read_json(directory / "progress.json")
            if job["status"] in {"running", "cancelling"}:
                source = Path(job["output_xml"]).parent / "progress.json"
                if self._fresh(source, job):
                    progress = read_json(source) or progress
            job["progress"] = progress if isinstance(progress, dict) else {}
            report = read_json(directory / "artifacts" / "run_report.json")
            sync_map = read_json(directory / "artifacts" / "sync_map.json")
            job["report"] = report
            job["sync_map"] = sync_map
            return job

    def listing(self):
        with self.lock:
            return [dict(j) for j in sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)]

    @staticmethod
    def _fresh(path, job):
        try:
            return not path.is_symlink() and path.is_file() and path.stat().st_mtime >= job["started_at"]
        except (OSError, TypeError):
            return False

    def _schedule(self):
        while not self.stopping.is_set():
            self.wake.clear()
            with self.lock:
                job = next((j for j in self.jobs.values() if j["status"] == "queued"), None)
                if job:
                    job.update(status="running", started_at=time.time())
                    self.save(job)
            if job:
                self._run(job)
            else:
                self.wake.wait(0.5)

    def _run(self, job):
        directory = self.directory(job)
        output = Path(job["output_xml"])
        command = [sys.executable, "-m", "acoustic_sync", "run", "--input_dir", job["input_dir"],
                   "--output_xml", str(output), "--fps", str(job["fps"]),
                   "--confidence-threshold", str(job["confidence_threshold"]),
                   "--workers", str(job["workers"]), "--cancel-file", str(directory / "cancel")]
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            with (directory / "console.log").open("wb") as log:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                           start_new_session=os.name != "nt")
                self.process = process
                while process.poll() is None:
                    with self.lock:
                        cancelled_at = job.get("cancel_requested_at")
                    if cancelled_at and time.time() - cancelled_at >= self.cancel_grace:
                        terminate_tree(process)
                        break
                    time.sleep(0.1)
            self._collect(job)
            with self.lock:
                job["returncode"] = process.returncode
                if job["status"] != "interrupted":
                    job["status"] = "cancelled" if job.get("cancel_requested_at") or process.returncode == 130 else ({0: "completed", 2: "partial"}.get(process.returncode, "failed"))
                    if job["status"] == "failed":
                        job["error"] = f"Pipeline exited with code {process.returncode}; see run.log."
        except Exception as exc:
            with self.lock:
                if job["status"] != "interrupted":
                    job.update(status="failed", error=str(exc))
        finally:
            with self.lock:
                self.process = None
                job["finished_at"] = time.time()
                self.save(job)

    def _collect(self, job):
        output = Path(job["output_xml"])
        directory = self.directory(job)
        artifacts = directory / "artifacts"
        artifacts.mkdir(exist_ok=True)
        found = []
        for name in sorted(ARTIFACTS):
            source = output if name == "timeline.xml" else output.parent / name
            if self._fresh(source, job):
                shutil.copyfile(source, artifacts / name)
                found.append(name)
        if "run.log" not in found:
            shutil.copyfile(directory / "console.log", artifacts / "run.log")
            found.append("run.log")
        progress = output.parent / "progress.json"
        if self._fresh(progress, job):
            shutil.copyfile(progress, directory / "progress.json")
        with self.lock:
            job["artifacts"] = found
