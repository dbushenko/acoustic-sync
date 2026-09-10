"""Clip records and interval packing, independent of XML serialization."""

from dataclasses import dataclass
from fractions import Fraction
import heapq
from pathlib import PureWindowsPath


@dataclass
class Clip:
    media: dict
    occurrence: int
    kind: str
    channel: int
    stream: dict | None
    start_seconds: Fraction
    seconds: Fraction
    source_rate: Fraction
    start: int = 0
    end: int = 0
    track: int = 0
    index: int = 0
    id: str = ""
    orphan: bool = False


def pack_intervals(clips, kind, track_offset=0):
    """Pack half-open frame intervals into the minimum number of tracks.

    Mutates each matching clip's one-based track/index. track_offset allows
    independent folder banks to follow existing sequence tracks.
    """
    tracks = []
    active, free = [], []
    for clip in sorted((c for c in clips if c.kind == kind),
                       key=lambda c: (c.start, c.occurrence, c.channel)):
        while active and active[0][0] <= clip.start:
            _, track = heapq.heappop(active)
            heapq.heappush(free, track)
        if free:
            track = heapq.heappop(free)
        else:
            track = len(tracks)
            tracks.append([])
        tracks[track].append(clip)
        clip.track, clip.index = track_offset + track + 1, len(tracks[track])
        heapq.heappush(active, (clip.end, track))
    return tracks


def source_folder(clip):
    """Use the immediate input-relative parent, keeping nested folders distinct."""
    relative = clip.media.get("relative_path")
    path = PureWindowsPath(relative or clip.media["file_path"])
    return path.parent.as_posix()


def pack_folders(clips, kind):
    """Reserve a contiguous track bank for each folder, in stable path order.

    An orphan uses its camera's bank too. Extra tracks are allocated only for
    overlapping recordings/channels within that folder, never for other folders.
    """
    folders = {}
    for clip in clips:
        if clip.kind == kind:
            # Keep camera sound ahead of standalone recorders, including when
            # both source types were stored in the same directory.
            standalone = kind == "audio" and not (clip.media.get("kind") == "video" and clip.media.get("video"))
            folders.setdefault((bool(standalone), source_folder(clip)), []).append(clip)
    tracks = []
    for folder in sorted(folders, key=lambda value: (value[0], value[1].casefold(), value[1])):
        tracks.extend(pack_intervals(folders[folder], kind, track_offset=len(tracks)))
    return tracks


__all__ = ["Clip", "pack_intervals", "pack_folders", "source_folder"]
