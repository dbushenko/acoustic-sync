"""Optional localhost web companion (install the ``web`` extra)."""
from pathlib import Path


def create_app(state_dir: Path | None = None):
    """Create the local application without importing web dependencies in the core."""
    from .app import create_app as factory

    return factory(state_dir)


__all__ = ["create_app"]
