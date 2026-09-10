"""Chunked spectral landmark hashing; memory is independent of recording length."""
from dataclasses import dataclass
import wave
import numpy as np
from scipy import ndimage, signal
from acoustic_sync.runtime import Cancellation


@dataclass(frozen=True)
class FingerprintSettings:
    n_fft: int = 2048
    hop: int = 128
    core_seconds: int = 20
    context_seconds: int = 3
    fanout: int = 8
    peaks_per_second: int = 40


def fingerprint_chunks(path: str, sample_rate: int, cancel: Cancellation, settings=None):
    """Yield (hash, sample-time) rows. Context permits pairs across chunk seams."""
    settings = settings or FingerprintSettings(n_fft=2048 if sample_rate == 22050 else 1024,
                                               hop=128 if sample_rate == 22050 else 64)
    nfft, hop = settings.n_fft, settings.hop
    core = (settings.core_seconds * sample_rate // hop) * hop
    context = (settings.context_seconds * sample_rate // hop) * hop
    with wave.open(path, "rb") as source:
        if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getframerate() != sample_rate:
            raise ValueError("Fingerprint input must be mono PCM16 at the manifest sample rate")
        total = source.getnframes()
        for core_start in range(0, total, core):
            cancel.check()
            left = max(0, core_start - context)
            right = min(total, core_start + core + context)
            source.setpos(left)
            x = np.frombuffer(source.readframes(right - left), dtype="<i2").astype(np.float32) / 32768
            if len(x) < nfft or np.max(np.abs(x), initial=0) < 1e-5:
                yield []
                continue
            _, times, z = signal.stft(x, fs=sample_rate, nperseg=nfft, noverlap=nfft-hop,
                                      boundary=None, padded=False)
            db = 20 * np.log10(np.maximum(np.abs(z), 1e-10))
            maximum = ndimage.maximum_filter(db, size=(9, 9), mode="constant", cval=-200)
            mask = (db == maximum) & (db > np.max(db, axis=0, keepdims=True) - 35) & (db > -85)
            mask[:max(2, int(100 * nfft / sample_rate))] = False
            frequencies, frames = np.nonzero(mask)
            scores = db[frequencies, frames]
            # Fixed time buckets cap memory and prevent loud sections dominating votes.
            buckets = ((times[frames] + left / sample_rate) * 10).astype(np.int64)
            order = np.lexsort((-scores, buckets))
            counts = {}
            peaks = []
            for pos in order:
                bucket = int(buckets[pos])
                if counts.get(bucket, 0) >= settings.peaks_per_second // 10:
                    continue
                counts[bucket] = counts.get(bucket, 0) + 1
                sample = left + int(round(times[frames[pos]] * sample_rate))
                peaks.append((sample, int(frequencies[pos])))
            peaks.sort()
            rows = []
            for i, (anchor, f1) in enumerate(peaks):
                if not core_start <= anchor < core_start + core:
                    continue
                targets = []
                for target, f2 in peaks[i+1:]:
                    dt = target - anchor
                    if dt > 2 * sample_rate:
                        break
                    if dt >= int(0.08 * sample_rate):
                        targets.append((target, f2))
                    if len(targets) >= settings.fanout:
                        break
                for target, f2 in targets:
                    delta = round((target - anchor) / (hop * 2))
                    key = ((f1 // 2) << 22) | ((f2 // 2) << 12) | delta
                    rows.append((key, anchor))
            yield list(set(rows))
