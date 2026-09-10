"""Check installed package assets, including after wheel installation in CI."""
import json
from importlib import metadata, resources


def main():
    dist = metadata.distribution("acoustic-sync")
    assert any(
        ep.name == "acoustic-sync" and ep.value == "acoustic_sync.cli:main"
        for ep in dist.entry_points
    ), "Console entry point missing"
    root = resources.files("acoustic_sync")
    schemas = list(root.joinpath("schemas").iterdir())
    schemas = [p for p in schemas if p.name.endswith(".json")]
    assert len(schemas) >= 2, "Expected media_manifest and sync_map JSON schemas"
    for schema in schemas:
        json.loads(schema.read_text(encoding="utf-8"))
    assert root.joinpath("web", "static", "index.html").is_file(), "Web assets missing"
    print(f"Installed acoustic-sync {dist.version}: entry point, {len(schemas)} schemas and web assets present")


if __name__ == "__main__":
    main()
