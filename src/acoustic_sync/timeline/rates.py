"""Public frame-rate API used by the command-line interface."""

from .xml import parse_frame_rate

parse_rate = parse_frame_rate

__all__ = ["parse_rate", "parse_frame_rate"]
