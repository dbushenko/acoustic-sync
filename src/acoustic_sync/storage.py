"""Filesystem ownership checks shared by independent pipeline stages."""
import json
from pathlib import Path
import shutil


def protect_output(path: Path, protected_paths, suffix=None, forbidden_roots=()):
    """Fail before writing when a destination aliases an input or scratch area."""
    destination = Path(path).resolve()
    if suffix and destination.suffix.lower() != suffix:
        raise ValueError(f"Output must have a {suffix} extension: {path}")
    for source in protected_paths:
        source = Path(source)
        if destination == source.resolve() or (destination.exists() and source.exists() and destination.samefile(source)):
            raise ValueError(f"Output must not replace an input file: {path}")
    if any(destination.is_relative_to(Path(root).resolve()) for root in forbidden_roots):
        raise ValueError(f"Output must be outside temporary reference directories: {path}")
    return destination


def cleanup_owned(path: Path, run_id: str, expected_parent: Path):
    path = path.absolute()
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise ValueError(f"Refusing unsafe cleanup target through a filesystem link: {path}")
    if path.name != run_id or path.resolve().parent != expected_parent.resolve():
        raise ValueError(f"Refusing cleanup outside owned temporary root: {path}")
    if not path.exists():
        return
    marker = path / ".owner.json"
    if not marker.is_file() or marker.is_symlink():
        raise ValueError(f"Missing ownership marker: {path}")
    owner = json.loads(marker.read_text(encoding="utf-8"))
    if owner != {"purpose": "acoustic-sync", "run_id": run_id}:
        raise ValueError(f"Ownership mismatch: {path}")
    shutil.rmtree(path)
