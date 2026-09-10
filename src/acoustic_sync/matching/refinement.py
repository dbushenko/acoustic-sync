"""Verify only shortlisted offsets using bounded, local FFT correlation windows."""
import wave
import numpy as np
from scipy import signal
from acoustic_sync.runtime import Cancellation


def _read(path, start, count):
    with wave.open(path, "rb") as wav:
        if start < 0 or start+count > wav.getnframes():
            return None
        wav.setpos(start)
        x = np.frombuffer(wav.readframes(count), dtype="<i2").astype(np.float64)
    if len(x) != count:
        return None
    # A gentle pre-emphasis suppresses rumble and improves acoustic-room matching.
    return signal.lfilter([1, -0.95], [1], x)


def refine(candidate: dict, a: dict, b: dict, sample_rate: int, cancel: Cancellation, frame_seconds: float) -> dict:
    """offset = start(b)-start(a); WAV positions account for stream origins."""
    delta = candidate["offset_samples"]
    with wave.open(a["wav_path"], "rb") as wav:
        an = wav.getnframes()
    with wave.open(b["wav_path"], "rb") as wav:
        bn = wav.getnframes()
    ao, bo = a["origin_samples"], b["origin_samples"]
    low = max(ao, delta + bo)
    high = min(ao + an, delta + bo + bn)
    overlap = (high-low)/sample_rate
    radius = round(0.12 * sample_rate)
    window = min(round(0.5 * sample_rate), high-low-2*radius)
    if window < sample_rate // 4:
        return {"verified": False, "reason": "insufficient_overlap", "overlap_seconds": max(0, overlap)}
    if candidate.get("anchor_positions"):
        starts = np.clip(np.array(candidate["anchor_positions"])-window//2, low+radius, high-window-radius).astype(np.int64)
    else:
        starts = np.linspace(low+radius, high-window-radius, 7).astype(np.int64)
    estimates = []
    correlations = []
    positions = []
    for position in dict.fromkeys(int(v) for v in starts):
        cancel.check()
        # Search A around the expected location of a fixed B window.
        x = _read(a["wav_path"], position-ao-radius, window+2*radius)
        y = _read(b["wav_path"], position-delta-bo, window)
        if x is None or y is None:
            continue
        y -= np.mean(y)
        energy_y = np.dot(y, y)
        if energy_y < 1e-8:
            continue
        numerator = signal.correlate(x, y, mode="valid", method="fft")
        sums = np.concatenate(([0.0], np.cumsum(x)))
        sums2 = np.concatenate(([0.0], np.cumsum(x*x)))
        energy_x = sums2[window:]-sums2[:-window] - (sums[window:]-sums[:-window])**2/window
        denominator = np.sqrt(np.maximum(energy_x * energy_y, 1e-15))
        normalized = np.abs(numerator/denominator)
        peak = int(np.argmax(normalized))
        score = float(min(1, normalized[peak]))
        if score >= 0.10 and 1 < peak < 2*radius-1:
            estimates.append(delta + peak-radius)
            correlations.append(score)
            positions.append(position)
    if len(estimates) < 3:
        return {"verified": False, "reason": "weak_local_verification", "overlap_seconds": overlap,
                "verification_windows": len(estimates)}
    offsets = np.array(estimates)
    original_estimates = list(estimates)
    # Reject isolated false correlation peaks only when a strong stationary
    # consensus exists. A distributed drift ramp cannot satisfy this gate.
    stationary_radius = max(2, round(sample_rate*min(.005, frame_seconds/4)))
    consensus = max((np.abs(offsets-v) <= stationary_radius for v in offsets), key=np.count_nonzero)
    if np.count_nonzero(consensus) >= max(3, np.ceil(len(offsets)*.75)):
        estimates = [v for v, keep in zip(estimates, consensus) if keep]
        positions = [v for v, keep in zip(positions, consensus) if keep]
        correlations = [v for v, keep in zip(correlations, consensus) if keep]
        offsets = np.array(estimates)
    median = int(np.median(offsets))
    spread = float((np.max(offsets)-np.min(offsets))/sample_rate)
    # Requiring temporal separation avoids claiming drift coverage from one short area.
    coverage = (max(positions)-min(positions)+window)/(high-low)
    drift_ppm = 0.0
    if max(positions) != min(positions):
        drift_ppm = float(np.polyfit(np.array(positions)-positions[0], offsets-offsets[0], 1)[0]*1e6)
    reason = "clock_drift_or_inconsistent_offset" if spread > frame_seconds else "verified"
    return {"verified": reason == "verified", "reason": reason, "offset_samples": median,
            "overlap_seconds": overlap, "overlap_start_samples": low, "overlap_end_samples": high,
            "verification_windows": len(estimates), "correlation": float(np.median(correlations)),
            "offset_spread_seconds": spread, "uncertainty_seconds": max(1/sample_rate, spread/2),
            "verification_coverage": min(1.0, coverage), "drift_ppm": drift_ppm,
            "window_offsets_samples": estimates, "raw_window_offsets_samples": original_estimates}
