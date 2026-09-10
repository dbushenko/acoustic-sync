"""Deterministic, non-repeating acoustic fixtures (no copyrighted media)."""
from pathlib import Path
import wave
import numpy as np
from scipy import signal


def recording(seconds=30, rate=22050, seed=91):
    rng = np.random.default_rng(seed)
    x = np.zeros(round(seconds*rate), dtype=np.float64)
    for start in np.arange(0, seconds, 0.13):
        duration = rng.uniform(0.10, 0.5)
        n = min(round(duration*rate), len(x)-round(start*rate))
        if n <= 0:
            continue
        t = np.arange(n)/rate
        f = rng.uniform(180, 7000)
        event = signal.chirp(t, f, duration, f*rng.uniform(0.7, 1.3))*np.sin(np.pi*np.arange(n)/n)**2
        x[round(start*rate):round(start*rate)+n] += event*rng.uniform(0.1, 0.6)
    x += signal.sosfilt(signal.butter(3, [200, 7000], btype="bandpass", fs=rate, output="sos"), rng.normal(0, 0.015, len(x)))
    return (x / max(1, np.max(np.abs(x))) * 0.75).astype(np.float32)


def write_wav(path: Path, x, rate=22050):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes((np.clip(x, -1, 1)*32767).astype("<i2").tobytes())


def manifest_for(paths, rate=22050):
    media = []
    for i, path in enumerate(paths):
        with wave.open(str(path), "rb") as wav:
            duration = wav.getnframes()/rate
        identity = f"media-{i}"
        stat = path.stat()
        media.append({"id": identity, "file_path": str(path.resolve()), "relative_path": path.name,
                      "kind": "audio", "duration_seconds": duration, "duration": str(duration),
                      "video": None, "status": "ready", "creation_time": None, "origin_seconds": "0",
                      "size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                      "audio_streams": [{"index": 0, "channels": 1, "sample_rate": rate, "depth": 16,
                                         "start_time": "0", "duration": str(duration)}],
                      "references": [{"id": identity+":0", "stream_index": 0, "wav_path": str(path.resolve()),
                                      "sample_rate": rate, "origin_samples": 0}]})
    return {"schema_version": "1.0", "sample_rate": rate, "media": media,
            "input_dir": str(paths[0].parent), "temp_dir": str(paths[0].parent)}
