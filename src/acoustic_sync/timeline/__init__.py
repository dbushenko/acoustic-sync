"""Standalone FCP7 timeline export (standard library only).

Offsets locate the media origin: video.start_time for video, otherwise the
first audio start_time (or explicit origin_seconds supplied by the pipeline).
Audio channels retain their delay from that origin.
All rounding is nearest frame, with half frames rounded away from zero.
"""

from .xml import export_xml, parse_frame_rate, validate_timeline
from .rates import parse_rate

__all__ = ["export_xml", "parse_rate", "parse_frame_rate", "validate_timeline"]
