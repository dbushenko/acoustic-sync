"""Verify source-release contents and separation from runtime wheel contents."""
from pathlib import Path
import tarfile
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    for archive in sorted((root / "dist").glob("*.tar.gz")):
        with tarfile.open(archive) as handle:
            files = {name.split("/", 1)[1] for name in handle.getnames() if "/" in name}
        for required in (
            "MANIFEST.in", "README.md", "pyproject.toml", "docs/installation.md",
            "requirements/dev.txt", "scripts/install.ps1", "scripts/install.sh",
            "scripts/run-web.ps1", "scripts/run-web.sh", "tests/fixtures/audio.py",
            "src/acoustic_sync/schemas/media_manifest.json",
            "src/acoustic_sync/schemas/sync_map.json", "src/acoustic_sync/web/static/index.html",
        ):
            assert required in files, f"{archive.name}: missing {required}"
        assert not any("__pycache__" in f or f.endswith((".pyc", ".pyo")) for f in files)
        print(f"{archive.name}: source release includes documentation, installers, locks, tests and assets")
    wheels = list((root / "dist").glob("*.whl"))
    assert wheels and list((root / "dist").glob("*.tar.gz")), "Build both distribution formats first"
    for archive in wheels:
        with zipfile.ZipFile(archive) as handle:
            for name in handle.namelist():
                top = name.split("/", 1)[0]
                assert top == "acoustic_sync" or top.endswith(".dist-info"), f"Unexpected wheel content: {name}"
        print(f"{archive.name}: wheel contains only application package and distribution metadata")


if __name__ == "__main__":
    main()
