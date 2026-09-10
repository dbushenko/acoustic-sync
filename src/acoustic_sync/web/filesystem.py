"""Directory listings for the local browser picker; never reads file contents."""
import os
from pathlib import Path
import string


def browse(path: str | None, *, initial: bool = False, show_xml: bool = False, offset: int = 0) -> dict:
    if not path:
        roots = [Path.home()]
        roots += [Path(f"{letter}:/") for letter in string.ascii_uppercase if Path(f"{letter}:/").is_dir()] if os.name == "nt" else [Path("/")]
        roots = list(dict.fromkeys(str(p.resolve()) for p in roots))
        return {"path": None, "parent": None, "entries": [
            {"name": "Home" if p == str(Path.home().resolve()) else p, "path": p, "kind": "directory"} for p in roots], "next_offset": None}
    directory = Path(path).expanduser()
    if not directory.is_absolute():
        raise ValueError("Choose an absolute folder path")
    if initial:
        while not directory.is_dir() and directory.parent != directory:
            directory = directory.parent
    directory = directory.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Choose a folder")
    entries = []
    with os.scandir(directory) as children:
        for child in children:
            if child.name.startswith("."):
                continue
            try:
                is_directory = child.is_dir()
                if is_directory or (show_xml and child.is_file() and Path(child.name).suffix.lower() == ".xml"):
                    entries.append({"name": child.name, "path": str(directory / child.name),
                                    "kind": "directory" if is_directory else "file"})
            except OSError:
                continue  # A disappeared entry should not prevent browsing its siblings.
    entries.sort(key=lambda e: (e["kind"] != "directory", e["name"].casefold(), e["name"]))
    limit = 200
    return {"path": str(directory), "parent": str(directory.parent) if directory.parent != directory else None,
            "entries": entries[offset:offset+limit], "next_offset": offset+limit if len(entries) > offset+limit else None}
