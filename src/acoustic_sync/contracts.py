"""JSON-only boundaries, strict schema versions, and atomic artifact writes."""
from importlib.resources import files
import json
import math
import os
from pathlib import Path
import tempfile
from fractions import Fraction

VERSION = "1.0"


def atomic_json(path: Path | str, value: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def validate(value: dict, kind: str) -> dict:
    import jsonschema
    def finite(node):
        if isinstance(node, float) and not math.isfinite(node):
            raise ValueError("JSON numbers must be finite")
        if isinstance(node, dict):
            for child in node.values():
                finite(child)
        elif isinstance(node, list):
            for child in node:
                finite(child)
    finite(value)
    schema = json.loads(files("acoustic_sync.schemas").joinpath(f"{kind}.json").read_text(encoding="utf-8"))
    integer_types = jsonschema.Draft202012Validator.TYPE_CHECKER.redefine("integer", lambda checker, instance: type(instance) is int)
    strict_validator = jsonschema.validators.extend(jsonschema.Draft202012Validator, type_checker=integer_types)
    strict_validator(schema).validate(value)
    if type(value["sample_rate"]) is not int:
        raise ValueError("sample_rate must be a JSON integer")
    ids = [m["id"] for m in value["media"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate media IDs")
    for item in value["media"]:
        if not math.isfinite(item["duration_seconds"]) or item["duration_seconds"] < 0:
            raise ValueError("invalid media duration")
        try:
            if Fraction(item["duration"]) < 0:
                raise ValueError("negative duration")
        except (ValueError, ZeroDivisionError) as error:
            raise ValueError("duration must be a finite nonnegative string number") from error
        if item["status"] != "error" and item["kind"] == "video":
            video = item.get("video")
            if not isinstance(video, dict) or not all(k in video for k in ("index", "width", "height", "frame_rate", "duration", "start_time")):
                raise ValueError("Playable video requires complete video metadata")
            if any(type(video[k]) is not int or video[k] < (0 if k == "index" else 1) for k in ("index", "width", "height")):
                raise ValueError("Invalid video index or dimensions")
            try:
                if Fraction(video["frame_rate"]) <= 0 or Fraction(video["duration"]) <= 0:
                    raise ValueError("invalid video rate or duration")
                Fraction(video["start_time"])
            except (ValueError, ZeroDivisionError) as error:
                raise ValueError("Video timing must be finite and valid") from error
        stream_ids = []
        for stream in item["audio_streams"]:
            stream_ids.append(stream["index"])
            try:
                if Fraction(stream["duration"]) <= 0:
                    raise ValueError("invalid audio duration")
                Fraction(stream["start_time"])
            except (ValueError, ZeroDivisionError) as error:
                raise ValueError("Audio timing must be finite and valid") from error
        if len(stream_ids) != len(set(stream_ids)):
            raise ValueError("Duplicate audio stream indices")
        reference_ids = []
        for reference in item.get("references", []):
            reference_ids.append(reference["id"])
            if type(reference.get("stream_index")) is not int or reference["stream_index"] not in stream_ids:
                raise ValueError("Reference requires a declared audio stream_index")
            if type(reference["sample_rate"]) is not int or reference["sample_rate"] != value["sample_rate"]:
                raise ValueError("Reference sample rate must match manifest sample rate")
        if len(reference_ids) != len(set(reference_ids)):
            raise ValueError("Duplicate reference IDs")
    if kind == "sync_map":
        assigned = []
        group_ids = [g["id"] for g in value["groups"]]
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Duplicate group IDs")
        for group in value["groups"]:
            members = [m["media_id"] for m in group["members"]]
            if group["reference_id"] not in members:
                raise ValueError("group reference must be a member")
            assigned.extend(members)
        assigned.extend(m["media_id"] for m in value["unmatched_clips"])
        if len(assigned) != len(set(assigned)) or set(assigned) != set(ids):
            raise ValueError("every media ID must occur once in groups or unmatched_clips")
    return value


def read_json(path: Path | str, kind: str) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        return validate(json.load(handle), kind)
