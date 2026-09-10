"""Run explicitly: python -m tests.performance.benchmark --files 100."""
import argparse
import json
import os
from pathlib import Path
import platform
import tempfile
import threading
import time
import psutil
from acoustic_sync.config import Config
from acoustic_sync.contracts import atomic_json
from acoustic_sync.matching.engine import match
from tests.fixtures.audio import recording, write_wav, manifest_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("benchmark_report.json"))
    args = parser.parse_args()
    done = threading.Event()
    rss = []
    def sample():
        while not done.wait(.1):
            rss.append(psutil.Process().memory_info().rss)
    thread = threading.Thread(target=sample, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="acoustic-benchmark-") as temporary:
            folder = Path(temporary)
            paths = []
            for i in range(args.files):
                group, part = divmod(i, 5)
                path = folder/f"group{group:03d}-clip{part}.wav"
                x = recording(24, seed=group+100)
                write_wav(path, x[part*3*22050:(part*3+8)*22050])
                paths.append(path)
            manifest = folder/"manifest.json"
            atomic_json(manifest, manifest_for(paths))
            started = time.monotonic()
            result = match(manifest, folder/"sync.json", Config())
            elapsed = time.monotonic()-started
            report = {"platform":platform.platform(),"processor":platform.processor(),"logical_cpus":os.cpu_count(),
                      "python":platform.python_version(),"files":args.files,"source_duration_seconds":args.files*8,
                      "elapsed_seconds":elapsed,"peak_rss_mb":max(rss,default=0)/1024**2,
                      "groups":len(result["groups"]),"unmatched":len(result["unmatched_clips"]),
                      "statistics":result["statistics"],"scope":"Module B; deterministic 8-second mono PCM sources, 5 overlapping clips per group"}
            atomic_json(args.output, report)
            print(json.dumps(report, indent=2))
    finally:
        done.set()
        thread.join()


if __name__ == "__main__":
    main()
