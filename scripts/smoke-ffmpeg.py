"""Optional end-to-end smoke using generated media; does not validate Premiere."""
import json
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np


def main():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} must be on PATH")
    with tempfile.TemporaryDirectory(prefix="acoustic-sync-smoke-") as folder:
        root = Path(folder)
        media = root / "media"
        media.mkdir()
        sr = 22050
        rng = np.random.default_rng(812)
        signal = (rng.standard_normal(sr * 12) * 4500).clip(-32768, 32767).astype("<i2")
        for name, samples in (("reference", signal), ("camera", signal[sr:])):
            with wave.open(str(media / f"{name}.wav"), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(sr)
                handle.writeframes(samples.tobytes())
        output = root / "result.xml"
        subprocess.run([
            sys.executable, "-m", "acoustic_sync", "run", "--input_dir", str(media),
            "--output_xml", str(output), "--fps", "25", "--workers", "1",
        ], check=True, timeout=180)
        sync = json.loads((root / "sync_map.json").read_text(encoding="utf-8"))
        assert sync["sample_rate"] == sr, "Unexpected reference sample rate"
        assert len(sync["groups"]) == 1, "Expected one matched group"
        assert not sync["unmatched_clips"], "Both synthetic clips must match"
        names = {item["id"]: Path(item["file_path"]).name for item in sync["media"]}
        offsets = {names[member["media_id"]]: member["offset_samples"]
                   for member in sync["groups"][0]["members"]}
        assert offsets == {"reference.wav": 0, "camera.wav": sr}, (
            f"Expected camera to start exactly one second later: {offsets}"
        )
        tree = ET.parse(output)
        assert tree.getroot().tag == "xmeml"
        assert tree.getroot().get("version") == "4"
        assert tree.findall(".//clipitem"), "No exported clip items"
        print("Synthetic FFmpeg-to-xmeml smoke passed; Premiere import remains a manual check.")


if __name__ == "__main__":
    main()
