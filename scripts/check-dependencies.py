"""Verify exact locks, pyproject agreement and active transitive dependency closure."""
from importlib import metadata
from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]


def read_lock(path, seen=None):
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen:
        return {}
    seen.add(path)
    locked = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-r "):
            entries = read_lock(path.parent / line[3:].strip(), seen)
        else:
            req = Requirement(line)
            specs = list(req.specifier)
            assert len(specs) == 1 and specs[0].operator == "==" and "*" not in specs[0].version, line
            if req.marker and not req.marker.evaluate({"extra": ""}):
                continue
            entries = {canonicalize_name(req.name): specs[0].version}
        for name, version in entries.items():
            assert name not in locked or locked[name] == version, f"Conflicting pins: {name}"
            locked[name] = version
    return locked


def main():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    profiles = {
        "runtime": project["project"]["dependencies"],
        "web": project["project"]["optional-dependencies"]["web"],
        "dev": project["project"]["optional-dependencies"]["dev"],
        "build": project["build-system"]["requires"],
    }
    for profile, direct in profiles.items():
        locked = read_lock(ROOT / "requirements" / f"{profile}.txt")
        for line in direct:
            req = Requirement(line)
            assert locked[canonicalize_name(req.name)] in req.specifier, f"pyproject mismatch: {line}"
        for name, version in locked.items():
            assert metadata.version(name) == version, f"Installed pin differs: {name}=={version}"
            for line in metadata.requires(name) or []:
                req = Requirement(line)
                if req.marker and not req.marker.evaluate({"extra": ""}):
                    continue
                dependency = canonicalize_name(req.name)
                assert dependency in locked, f"{profile}: missing transitive pin {name} -> {line}"
                assert locked[dependency] in req.specifier, f"{profile}: incompatible dependency {name} -> {line}"
        print(f"{profile}: {len(locked)} installed exact pins; active dependency closure OK")


if __name__ == "__main__":
    main()
