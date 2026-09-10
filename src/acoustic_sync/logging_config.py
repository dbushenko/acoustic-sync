import logging
from pathlib import Path


def configure(path: Path | None = None, verbose: bool = False):
    logger = logging.getLogger("acoustic_sync")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    handlers = [logging.StreamHandler()]
    if path:
        if path.is_symlink():
            raise ValueError(f"Refusing to write log through a symbolic link: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(path, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.propagate = False
