"""Translate FFprobe metadata into portable JSON, excluding thumbnail streams."""
from fractions import Fraction
import math
from pathlib import Path
from acoustic_sync.runtime import Cancellation, probe_json
from acoustic_sync.recording_time import metadata_candidates


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def probe(item: dict, cancel: Cancellation, timeout: float) -> dict:
    data = probe_json(Path(item["file_path"]), cancel, timeout)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
              and s.get("disposition", {}).get("timed_thumbnails", 0) == 0]
    # Main streams have a valid average frame rate; thumbnails often report 0/0.
    valid = []
    for stream in videos:
        try:
            rate = Fraction(stream.get("avg_frame_rate", "0/0"))
            if 0 < rate <= 240:
                valid.append(stream)
        except (ValueError, ZeroDivisionError):
            pass
    videos = valid or [s for s in videos if s.get("nb_frames") != "1"]
    primary = max(videos, key=lambda s: (s.get("width", 0) * s.get("height", 0), -s["index"]), default=None)
    duration = number(fmt.get("duration"))
    video = None
    warnings = []
    if primary:
        rate = primary.get("avg_frame_rate", "0/0")
        try:
            if Fraction(rate) <= 0:
                raise ValueError("rate")
        except (ValueError, ZeroDivisionError):
            rate = primary.get("r_frame_rate", "25/1")
        parsed_rate = Fraction(rate)
        if not 0 < parsed_rate <= 240:
            raise ValueError("Main video frame rate must be positive and at most 240")
        if parsed_rate.denominator != 1 and (parsed_rate * Fraction(1001, 1000)).denominator != 1:
            nominal = Fraction(primary.get("r_frame_rate", "0/1"))
            if not 0 < nominal <= 240 or (nominal.denominator != 1 and (nominal * Fraction(1001, 1000)).denominator != 1):
                raise ValueError("Variable frame rate has no representable nominal rate; transcode to CFR before export")
            rate = str(nominal)
            warnings.append("Variable frame rate: using nominal source rate; frame-exact Premiere interpretation is not guaranteed")
        video = {"index": primary["index"], "width": primary["width"], "height": primary["height"],
                 "frame_rate": rate, "start_time": str(primary.get("start_time", "0")),
                 "duration": str(number(primary.get("duration"), duration)),
                 "time_base": primary.get("time_base"), "nb_frames": primary.get("nb_frames"),
                 "field_order": primary.get("field_order", "unknown"),
                 "pixel_aspect_ratio": primary.get("sample_aspect_ratio", "1:1")}
        duration = number(video["duration"], duration)
        if primary.get("r_frame_rate") != rate:
            warnings.append("Possible variable frame rate: frame-exact Premiere interpretation is not guaranteed")
    audio = []
    for stream in streams:
        if stream.get("codec_type") != "audio":
            continue
        audio.append({"index": stream["index"], "channels": int(stream.get("channels", 1)),
                      "sample_rate": int(stream.get("sample_rate", 48000)),
                      "depth": int(stream.get("bits_per_raw_sample") or stream.get("bits_per_sample") or 16),
                      "start_time": str(stream.get("start_time", "0")),
                      "duration": str(number(stream.get("duration"), number(fmt.get("duration"), duration))),
                      "channel_layout": stream.get("channel_layout", "unknown")})
    if not video and not audio:
        raise ValueError("No playable video or audio streams")
    if duration <= 0:
        duration = max((number(s["duration"]) for s in audio), default=0.0)
    if duration <= 0:
        raise ValueError("Cannot establish a positive media duration")
    origin = video["start_time"] if video else (audio[0]["start_time"] if audio else "0")
    return {**item, "kind": "video" if video else "audio", "duration_seconds": duration,
            "duration": str(duration), "video": video, "audio_streams": audio,
            "origin_seconds": str(origin), "creation_time": fmt.get("tags", {}).get("creation_time"),
            "recording_time_candidates": metadata_candidates(fmt.get("tags", {}),
                ([primary] if primary else []) + [s for s in streams if s.get("codec_type") == "audio"]),
            "status": "ready" if audio else "no_audio", "warnings": warnings, "references": []}
