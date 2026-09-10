"""Deterministic discovery without following directory links."""
import hashlib
import os
from pathlib import Path

EXTENSIONS = {".mp4", ".mov", ".mxf", ".mkv", ".avi", ".mts", ".m2ts", ".webm", ".wav", ".mp3", ".flac", ".aac", ".m4a", ".aif", ".aiff", ".ogg", ".wma"}
EXCLUDED = {"tmp_audio", ".git", ".venv", ".runtime", "__pycache__", "node_modules"}


def scan(root: Path, exclude: list[Path] | None = None) -> list[dict]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Input must be a directory: {root}")
    blocked = {p.resolve() for p in (exclude or [])}
    result = []
    def on_error(error):
        raise error  # An unreadable subtree must not silently disappear.
    for directory, names, files in os.walk(root, followlinks=False, onerror=on_error):
        names[:] = sorted(n for n in names if n not in EXCLUDED and not (Path(directory) / n).is_symlink()
                          and not (Path(directory) / n).is_junction() and (Path(directory) / n).resolve() not in blocked)
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or path.suffix.lower() not in EXTENSIONS or path.resolve() in blocked:
                continue
            relative = path.relative_to(root).as_posix()
            stat = path.stat()
            result.append({"id": hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24],
                           "file_path": str(path.resolve()), "relative_path": relative,
                           "size": stat.st_size, "mtime_ns": stat.st_mtime_ns})
    return sorted(result, key=lambda item: item["relative_path"].casefold())
