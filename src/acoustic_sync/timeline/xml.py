"""FCP7 xmeml v4 export, rational timing, interval packing and validation.

Source in/out/duration use the source rate; timeline start/end use the sequence
rate. Container stream timestamps are not timecode. They are preserved in
logginginfo, and used to retain audio/video delays without trimming channels.
Unsupported rates fail instead of silently exporting a different frame rate.
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path, PureWindowsPath
import tempfile
from urllib.parse import quote, urlsplit
import xml.etree.ElementTree as ET

from .placement import order_sections, section_date
from .tracks import Clip as _Clip, pack_folders as _pack, source_folder


def parse_frame_rate(value: str = "25") -> Fraction:
    """Parse integer/rational rates and common NTSC decimal aliases exactly."""
    aliases = {"23.976": "24000/1001", "23.98": "24000/1001",
               "29.97": "30000/1001", "59.94": "60000/1001",
               "119.88": "120000/1001"}
    text = str(value).strip()
    try:
        rate = Fraction(aliases.get(text, text))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"Invalid frame rate: {value!r}") from exc
    if rate <= 0 or not (rate.denominator == 1 or
                         (rate * Fraction(1001, 1000)).denominator == 1):
        raise ValueError(f"Frame rate cannot be represented in FCP7: {value!r}")
    return rate


def _number(value, field: str) -> Fraction:
    try:
        return Fraction(str(value))
    except (ValueError, ZeroDivisionError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc


def _positive_int(value, field: str) -> int:
    number = _number(value, field)
    if isinstance(value, bool) or number.denominator != 1 or number <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return int(number)


def _round(value: Fraction) -> int:
    if value < 0:
        return -_round(-value)
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _sub(parent, tag, value=None, **attrs):
    child = ET.SubElement(parent, tag, attrs)
    if value is not None:
        child.text = str(value)
    return child


def _rate(parent, fps):
    rate = _sub(parent, "rate")
    ntsc = fps.denominator != 1
    _sub(rate, "timebase", int(fps * Fraction(1001, 1000)) if ntsc else int(fps))
    _sub(rate, "ntsc", "TRUE" if ntsc else "FALSE")


def _pathurl(path: str) -> str:
    windows = PureWindowsPath(path)
    if windows.is_absolute():
        # Generate the same localhost URL form as Premiere's FCP7 exporter.
        if windows.drive.startswith("\\\\"):
            return windows.as_uri()
        return "file://localhost/" + quote(windows.as_posix(), safe="/")
    return Path(path).expanduser().resolve().as_uri()


def _duration(data, fallback=None) -> Fraction:
    value = data.get("duration")
    if value is None:
        value = data.get("duration_seconds", fallback)
    duration = _number(value, "duration")
    if duration <= 0:
        raise ValueError("Media/stream durations must be positive")
    return duration


def _protect_output(output_xml, media):
    """Reject source aliases before export can create directories or files."""
    output = Path(output_xml)
    destination = output.resolve()
    if output.suffix.lower() != ".xml" or destination.suffix.lower() != ".xml":
        raise ValueError(f"Output must have a .xml extension: {output}")
    for item in media:
        source = Path(item["file_path"])
        if destination == source.resolve() or (
                destination.exists() and source.exists() and destination.samefile(source)):
            raise ValueError(f"Output must not replace an original source file: {output}")
    return output


def _components(media, occurrence, offset, fps):
    video = media.get("video") if media["kind"] == "video" else None
    streams = media.get("audio_streams", [])
    duration = _duration(media)
    source_rate = parse_frame_rate(video["frame_rate"]) if video else fps
    origin = _number(media.get("origin_seconds", video.get("start_time", "0") if video
                               else streams[0].get("start_time", "0") if streams else "0"),
                     "media origin")
    result = []
    if video:
        _positive_int(video["width"], "video.width")
        _positive_int(video["height"], "video.height")
        result.append(_Clip(media, occurrence, "video", 1, None, offset,
                            _duration(video, duration), source_rate))
    channel = 0
    for stream in streams:
        channels = _positive_int(stream["channels"], "audio.channels")
        _positive_int(stream["sample_rate"], "audio.sample_rate")
        _positive_int(stream.get("depth", 16), "audio.depth")
        delay = _number(stream.get("start_time", "0"), "audio.start_time") - origin
        for _ in range(channels):
            channel += 1
            result.append(_Clip(media, occurrence, "audio", channel, stream,
                                offset + delay, _duration(stream, duration), source_rate))
    if not result:
        raise ValueError(f"Media {media['id']!r} has no usable streams")
    return result


def _video_format(parent, fps, width, height):
    characteristics = _sub(parent, "samplecharacteristics")
    _rate(characteristics, fps)
    for tag, value in (("width", width), ("height", height), ("anamorphic", "FALSE"),
                       ("pixelaspectratio", "square"), ("fielddominance", "none")):
        _sub(characteristics, tag, value)


def _file(parent, clip, file_id, defined):
    file = _sub(parent, "file", id=file_id)
    if file_id in defined:
        return
    defined.add(file_id)
    media = clip.media
    _sub(file, "name", PureWindowsPath(media["file_path"]).name)
    _sub(file, "pathurl", _pathurl(media["file_path"]))
    _rate(file, clip.source_rate)
    durations = [_duration(media)]
    durations.extend(_duration(s, durations[0]) for s in media.get("audio_streams", []))
    if media.get("video"):
        durations.append(_duration(media["video"], durations[0]))
    _sub(file, "duration", max(1, _round(max(durations) * clip.source_rate)))
    source = _sub(file, "media")
    if media.get("video") and media["kind"] == "video":
        video = media["video"]
        _video_format(_sub(source, "video"), clip.source_rate, video["width"], video["height"])
    streams = media.get("audio_streams", [])
    if streams:
        audio = _sub(source, "audio")
        chars = _sub(audio, "samplecharacteristics")
        _sub(chars, "depth", streams[0].get("depth", 16))
        _sub(chars, "samplerate", streams[0]["sample_rate"])
        _sub(audio, "channelcount", sum(int(s["channels"]) for s in streams))


def _source_bins(parent, clips, files, sequence):
    """Declare one browser master per source, organized by its relative path.

    PureWindowsPath accepts both scanner POSIX separators and Windows paths;
    no filesystem access is needed when exporting an archived sync map.
    """
    top = _sub(parent, "bin", id="source-bin-1")
    _sub(top, "name", "Source media")
    folders = {(): _sub(top, "children")}
    sources = {}
    for clip in clips:
        sources.setdefault(clip.media["id"], clip)
    for mid, clip in sorted(sources.items(), key=lambda pair: (
            pair[1].media.get("relative_path", pair[1].media["file_path"]), pair[0])):
        relative = PureWindowsPath(clip.media.get("relative_path", ""))
        parts = relative.parent.parts
        if relative.anchor or ".." in parts:
            raise ValueError(f"Invalid source relative path: {relative}")
        for depth in range(1, len(parts) + 1):
            key = parts[:depth]
            if key not in folders:
                folder = _sub(folders[key[:-1]], "bin", id=f"source-bin-{len(folders) + 1}")
                _sub(folder, "name", key[-1])
                folders[key] = _sub(folder, "children")
        master_id = "masterclip-" + files[mid][5:]
        master = _sub(folders[parts], "clip", id=master_id)
        _sub(master, "name", PureWindowsPath(clip.media["file_path"]).name)
        _sub(master, "masterclipid", master_id)
        _sub(master, "ismasterclip", "TRUE")
        _rate(master, clip.source_rate)
        seconds = [_duration(clip.media)]
        seconds.extend(_duration(s, seconds[0]) for s in clip.media.get("audio_streams", []))
        if clip.media.get("video"):
            seconds.append(_duration(clip.media["video"], seconds[0]))
        _sub(master, "duration", max(1, _round(max(seconds) * clip.source_rate)))
        _sub(master, "in", -1)
        _sub(master, "out", -1)
        # Browser clips need explicit video/audio tracks for Premiere's importer.
        # Reuse source metadata, but never copy sequence placement into a master.
        components = [item for item in sequence.findall(".//clipitem")
                      if item.findtext("masterclipid") == master_id]
        ids = {item.get("id"): "source-" + item.get("id") for item in components}
        master_media = _sub(master, "media")
        for original in components:
            item = deepcopy(original)
            item.set("id", ids[original.get("id")])
            item.find("start").text = "-1"
            item.find("end").text = "-1"
            kind = item.findtext("sourcetrack/mediatype")
            section = master_media.find(kind)
            if section is None:
                section = _sub(master_media, kind)
            track = _sub(section, "track")
            for link in item.findall("link"):
                target = link.findtext("linkclipref")
                link.find("linkclipref").text = ids[target]
                linked = next(c for c in components if c.get("id") == target)
                link.find("trackindex").text = linked.findtext("sourcetrack/trackindex")
                link.find("clipindex").text = "1"
            # File definitions already occur in the sequence; reference them once.
            file = item.find("file")
            file.clear()
            file.set("id", files[mid])
            track.append(item)
            _sub(track, "enabled", "TRUE")
            _sub(track, "locked", "FALSE")


def export_xml(sync_map: dict, output_xml: Path, fps: str = "25",
               width: int | None = None, height: int | None = None) -> dict:
    """Export a sync-map 1.0 as an atomically written FCP7 sequence.

    Groups and orphans sort together by their earliest available recording date.
    Metadata timestamps take priority over filename hints; undated sections are appended
    after dated sections. Each source folder has its own stable track bank.
    Error and zero-duration media are reported in errors/skipped and omitted.
    Playable extraction_failed media retain their original streams.
    Invalid contracts raise ValueError
    before touching the output. The return value is JSON-serializable.
    """
    output_xml = _protect_output(output_xml, sync_map.get("media", []))
    sequence_rate = parse_frame_rate(fps)
    if sync_map.get("schema_version") != "1.0":
        raise ValueError("Expected sync-map schema_version '1.0'")
    sample_rate = _positive_int(sync_map.get("sample_rate"), "sample_rate")
    media_by_id = {}
    skipped = []
    for media in sync_map.get("media", []):
        mid = media.get("id")
        if not isinstance(mid, str) or not mid or mid in media_by_id:
            raise ValueError(f"Missing or duplicate media id: {mid!r}")
        if media.get("kind") not in ("audio", "video"):
            raise ValueError(f"Invalid media kind for {mid}")
        if media.get("status") not in ("ready", "no_audio", "extraction_failed", "error"):
            raise ValueError(f"Invalid media status for {mid}")
        if not isinstance(media.get("file_path"), str) or not media["file_path"]:
            raise ValueError(f"Missing file_path for {mid}")
        media_by_id[mid] = media
        if media["status"] == "error":
            skipped.append({"media_id": mid, "reason": media.get("error", "error")})
        else:
            duration = _number(media.get("duration", media.get("duration_seconds")), "duration")
            if duration < 0:
                raise ValueError(f"Negative media duration for {mid}")
            if duration == 0:
                skipped.append({"media_id": mid, "reason": "Unplayable media: zero duration"})
    skipped_ids = {entry["media_id"] for entry in skipped}
    sections, seen, group_ids = [], set(), set()
    for group in sync_map.get("groups", []):
        gid = group.get("id")
        if not isinstance(gid, str) or not gid or gid in group_ids:
            raise ValueError(f"Missing or duplicate group id: {gid!r}")
        group_ids.add(gid)
        members = group.get("members", [])
        if not members or group.get("reference_id") not in [m["media_id"] for m in members]:
            raise ValueError(f"Group {gid!r} must contain its reference")
        entries = []
        for member in members:
            mid = member["media_id"]
            if mid not in media_by_id or mid in seen:
                raise ValueError(f"Unknown or repeated grouped media: {mid!r}")
            samples = member.get("offset_samples")
            if isinstance(samples, bool) or not isinstance(samples, int) or samples < 0:
                raise ValueError("offset_samples must be a nonnegative integer")
            confidence = _number(member.get("confidence"), "confidence")
            if not 0 <= confidence <= 100:
                raise ValueError("confidence must lie between 0 and 100")
            seen.add(mid)
            entries.append((mid, Fraction(samples, sample_rate)))
        sections.append((gid, False, entries))
    orphan_ids, orphan_reasons = [], {}
    for orphan in sync_map.get("unmatched_clips", []):
        mid = orphan["media_id"]
        if mid not in media_by_id or mid in seen or mid in orphan_ids:
            raise ValueError(f"Unknown, grouped or repeated unmatched media: {mid!r}")
        orphan_ids.append(mid)
        orphan_reasons[mid] = orphan.get("reason") or "No synchronization match"
    orphan_ids.extend(mid for mid in media_by_id if mid not in seen and mid not in orphan_ids)
    orphan_sections = [(f"[NOT_SYNCED] {mid}", True, [(mid, Fraction(0))]) for mid in orphan_ids]
    sections = order_sections(sections + orphan_sections, media_by_id)
    clips, markers = [], []
    cursor = 0
    gap = _round(2 * sequence_rate)
    occurrence = 0
    for name, orphan, entries in sections:
        components = []
        for mid, offset in entries:
            media = media_by_id[mid]
            if mid in skipped_ids:
                continue
            occurrence += 1
            components.extend(_components(media, occurrence, offset, sequence_rate))
        if not components:
            continue
        shift = -min(Fraction(0), min(c.start_seconds for c in components))
        section_start = cursor
        for clip in components:
            clip.orphan = orphan
            clip.start = cursor + _round((clip.start_seconds + shift) * sequence_rate)
            clip.end = max(clip.start + 1, cursor + _round(
                (clip.start_seconds + shift + clip.seconds) * sequence_rate))
            clip.id = f"clipitem-{len(clips) + 1}"
            clips.append(clip)
        section_end = max(c.end for c in components)
        reason = (orphan_reasons.get(entries[0][0], "Not assigned to a synchronization group")
                  if orphan else "Placement between disconnected groups is arbitrary")
        markers.append({"name": name if orphan else f"[RELATIVE_TIMING_UNKNOWN] {name}",
                        "start": section_start, "end": section_end, "reason": reason,
                        "orphan": orphan, "shift_seconds": str(shift),
                        "recording_time": section_date((name, orphan, entries), media_by_id)})
        cursor = section_end + gap
    first_video = next((c.media["video"] for c in clips if c.kind == "video" and not c.orphan),
                       next((c.media["video"] for c in clips if c.kind == "video"), None))
    width = _positive_int(width if width is not None else
                          (first_video["width"] if first_video else 1920), "width")
    height = _positive_int(height if height is not None else
                           (first_video["height"] if first_video else 1080), "height")
    tracks, orphan_tracks = {}, {}
    for kind in ("video", "audio"):
        tracks[kind] = _pack(clips, kind)
        # Retain report keys as counts of tracks containing unmatched clips;
        # these tracks can also contain synchronized clips at other times.
        orphan_tracks[kind] = sum(any(c.orphan for c in track) for track in tracks[kind])
    duration = max((c.end for c in clips), default=0)
    root = ET.Element("xmeml", {"version": "4"})
    sequence = _sub(root, "sequence", id="sequence-1")
    _sub(sequence, "name", "Acoustic Sync")
    _sub(sequence, "duration", duration)
    _rate(sequence, sequence_rate)
    media_node = _sub(sequence, "media")
    files, defined, occurrences = {}, set(), {}
    for clip in clips:
        files.setdefault(clip.media["id"], f"file-{len(files) + 1}")
        occurrences.setdefault(clip.occurrence, []).append(clip)
    for kind in ("video", "audio"):
        node = _sub(media_node, kind)
        if kind == "video":
            _video_format(_sub(node, "format"), sequence_rate, width, height)
        else:
            _sub(node, "numOutputChannels", 2)
            chars = _sub(_sub(node, "format"), "samplecharacteristics")
            _sub(chars, "depth", 24)
            _sub(chars, "samplerate", 48000)
            outputs = _sub(node, "outputs")
            for channel in (1, 2):
                group = _sub(outputs, "group")
                _sub(group, "index", channel)
                _sub(group, "numchannels", 1)
                _sub(group, "downmix", 0)
                _sub(_sub(group, "channel"), "index", channel)
        for track in tracks[kind]:
            track_node = _sub(node, "track")
            for clip in track:
                item = _sub(track_node, "clipitem", id=clip.id)
                _sub(item, "masterclipid", "masterclip-" + files[clip.media["id"]][5:])
                _sub(item, "name", PureWindowsPath(clip.media["file_path"]).name)
                _sub(item, "enabled", "TRUE")
                source_duration = max(1, _round(clip.seconds * clip.source_rate))
                _sub(item, "duration", source_duration)
                _rate(item, clip.source_rate)
                for tag, value in (("start", clip.start), ("end", clip.end),
                                   ("in", 0), ("out", source_duration)):
                    _sub(item, tag, value)
                _file(item, clip, files[clip.media["id"]], defined)
                source = _sub(item, "sourcetrack")
                _sub(source, "mediatype", kind)
                _sub(source, "trackindex", clip.channel)
                for linked in occurrences[clip.occurrence]:
                    link = _sub(item, "link")
                    for tag, value in (("linkclipref", linked.id), ("mediatype", linked.kind),
                                       ("trackindex", linked.track), ("clipindex", linked.index)):
                        _sub(link, tag, value)
                    # groupindex denotes a stereo pair, not an arbitrary set
                    # of linked channels. Leave discrete/multichannel audio mono.
                    if linked.kind == "audio" and int(linked.stream["channels"]) == 2:
                        _sub(link, "groupindex", linked.media["audio_streams"].index(linked.stream) + 1)
                logging = _sub(item, "logginginfo")
                metadata = {"media_id": clip.media["id"], "source": clip.media,
                            "source_audio_stream_index": clip.stream["index"] if clip.stream else None,
                            "source_channel": clip.channel}
                _sub(logging, "lognote", json.dumps(metadata, ensure_ascii=False, sort_keys=True))
                _sub(logging, "originalvideofilename" if kind == "video" else
                     "originalaudiofilename", clip.media["file_path"])
            _sub(track_node, "enabled", "TRUE")
            _sub(track_node, "locked", "FALSE")
            if kind == "audio":
                _sub(track_node, "outputchannelindex", (track[0].track - 1) % 2 + 1)
    for marker in markers:
        node = _sub(sequence, "marker")
        _sub(node, "name", marker["name"])
        _sub(node, "comment", ("[NOT_SYNCED] Review reason: " if marker["orphan"] else
                               "[RELATIVE_TIMING_UNKNOWN] ") + str(marker["reason"]))
        _sub(node, "in", marker["start"])
        _sub(node, "out", marker["end"])
        if marker["recording_time"]:
            hint = marker["recording_time"]
            node.find("comment").text += f"; Approximate recording date: {hint['value']} ({hint['source']}, {hint['precision']})"
    _source_bins(root, clips, files, sequence)
    ET.indent(root, space="  ")
    payload = b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + ET.tostring(root, encoding="utf-8") + b"\n"
    validation = validate_timeline(payload.decode("utf-8"))
    if not validation["valid"]:
        raise ValueError("Generated invalid timeline: " + "; ".join(validation["errors"]))
    output_xml.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_xml.parent, prefix=".timeline-",
                                         suffix=".xml", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
        temporary.replace(output_xml)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"output_xml": str(output_xml), "fps": str(sequence_rate),
            "duration_frames": duration, "duration_seconds": float(Fraction(duration, 1) / sequence_rate),
            "width": width, "height": height, "video_tracks": len(tracks["video"]),
            "audio_tracks": len(tracks["audio"]), "clip_count": len(clips),
            "track_folders": {kind: [{"track": index, "folder": source_folder(track[0])}
                                      for index, track in enumerate(tracks[kind], 1)]
                              for kind in ("video", "audio")},
            "orphan_video_tracks": orphan_tracks["video"], "orphan_audio_tracks": orphan_tracks["audio"],
            "media_count": len(files), "group_count": sum(not m["orphan"] for m in markers),
            "orphan_count": sum(m["orphan"] for m in markers), "markers": markers,
            "errors": skipped, "skipped": skipped,
            "warnings": [f"Skipped {s['media_id']}: {s['reason']}" for s in skipped],
            "validation": validation}


def validate_timeline(xml: Path | str | ET.Element | ET.ElementTree) -> dict:
    """Check exported XML; return {valid, errors, clip_count} without raising.

    Accept a path, XML string, Element, or ElementTree. Checks cover rates,
    bounds, packing, file references, channel mappings, and reciprocal links
    with their actual one-based track and clip indices. This is a structural
    validator, not an NLE import test or an exhaustive FCP DTD validator.
    """
    errors = []
    try:
        if isinstance(xml, ET.Element):
            root = xml
        elif isinstance(xml, ET.ElementTree):
            root = xml.getroot()
        elif isinstance(xml, str) and xml.lstrip().startswith("<"):
            root = ET.fromstring(xml)
        else:
            root = ET.parse(xml).getroot()
    except (ET.ParseError, OSError, ValueError, TypeError, UnicodeError) as exc:
        return {"valid": False, "errors": [f"Cannot read XML: {exc}"], "clip_count": 0}
    if root.tag != "xmeml" or root.get("version") != "4":
        errors.append("Expected xmeml version 4")
    sequence = root.find("sequence")
    if sequence is None:
        sequence = root.find("project/children/sequence")
    if sequence is None:
        return {"valid": False, "errors": errors + ["Missing sequence"], "clip_count": 0}

    def integer(node, tag, default=-1):
        try:
            return int(node.findtext(tag, ""))
        except (ValueError, TypeError):
            errors.append(f"Invalid integer {tag} in {node.tag} {node.get('id', '')}")
            return default

    def rate(node):
        r = node.find("rate")
        if r is None:
            errors.append(f"Missing rate in {node.tag}")
            return Fraction(25)
        base = integer(r, "timebase")
        ntsc = r.findtext("ntsc")
        if base <= 0 or ntsc not in ("TRUE", "FALSE"):
            errors.append("Invalid rate")
            return Fraction(25)
        return Fraction(base * 1000, 1001) if ntsc == "TRUE" else Fraction(base)

    seq_rate = rate(sequence)
    duration = integer(sequence, "duration")
    if duration < 0:
        errors.append("Negative sequence duration")
    files = {}
    for file in root.findall(".//file"):
        fid = file.get("id")
        if not fid:
            errors.append("File without id")
        if len(file):
            if fid in files:
                errors.append(f"Duplicate file definition {fid}")
            files[fid] = file
            if urlsplit(file.findtext("pathurl", "")).scheme != "file":
                errors.append(f"Missing/invalid file URL {fid}")
            rate(file)
            if integer(file, "duration") <= 0:
                errors.append(f"Invalid file duration {fid}")
    masters = {}
    for master in root.findall(".//bin/children/clip"):
        mid = master.get("id")
        if not mid or mid in masters:
            errors.append(f"Missing/duplicate master clip id {mid}")
        masters[mid] = master
        if master.findtext("masterclipid") != mid or master.findtext("ismasterclip") != "TRUE":
            errors.append(f"Invalid master clip {mid}")
        file = master.find(".//file")
        if file is None or file.get("id") not in files:
            errors.append(f"Dangling master file reference {mid}")
    items, locations = {}, {}
    for kind in ("video", "audio"):
        for ti, track in enumerate(sequence.findall(f"media/{kind}/track"), 1):
            if track.findtext("enabled") != "TRUE":
                errors.append(f"Disabled {kind} track {ti}")
            last_end = 0
            for ci, item in enumerate(track.findall("clipitem"), 1):
                cid = item.get("id")
                if root.find("bin") is not None or root.find("project") is not None:
                    master = masters.get(item.findtext("masterclipid"))
                    if master is None:
                        errors.append(f"Dangling master clip reference {cid}")
                    elif (item.find("file") is not None and master.find(".//file") is not None
                          and item.find("file").get("id") != master.find(".//file").get("id")):
                        errors.append(f"Master/source mismatch {cid}")
                if not cid or cid in items:
                    errors.append(f"Missing/duplicate clip id {cid}")
                items[cid], locations[cid] = item, (kind, ti, ci)
                start, end = integer(item, "start"), integer(item, "end")
                source_in, source_out = integer(item, "in"), integer(item, "out")
                source_duration = integer(item, "duration")
                source_rate = rate(item)
                if item.find("samplecharacteristics") is not None:
                    errors.append(f"samplecharacteristics must be under file/media, not clipitem {cid}")
                if start < last_end:
                    errors.append(f"Track overlap or unordered clips at {cid}")
                last_end = max(last_end, end)
                if start < 0 or end <= start or end > duration:
                    errors.append(f"Invalid timeline bounds {cid}")
                if source_in < 0 or source_out <= source_in or source_out > source_duration:
                    errors.append(f"Invalid source bounds {cid}")
                if abs(Fraction(end - start, 1) / seq_rate -
                       Fraction(source_out - source_in, 1) / source_rate) > 1 / seq_rate + 1 / source_rate:
                    errors.append(f"Source/timeline duration mismatch {cid}")
                if item.findtext("enabled") != "TRUE":
                    errors.append(f"Disabled clip {cid}")
                file = item.find("file")
                definition = files.get(file.get("id")) if file is not None else None
                if definition is None:
                    errors.append(f"Dangling file reference {cid}")
                elif source_out > integer(definition, "duration"):
                    errors.append(f"Source exceeds file duration {cid}")
                source = item.find("sourcetrack")
                if source is None or source.findtext("mediatype") != kind:
                    errors.append(f"Invalid source track {cid}")
                else:
                    channel = integer(source, "trackindex")
                    maximum = integer(definition, "media/audio/channelcount") if kind == "audio" and definition is not None else 1
                    if not 1 <= channel <= maximum:
                        errors.append(f"Invalid source channel {cid}")
    for cid, item in items.items():
        refs = [link.findtext("linkclipref") for link in item.findall("link")]
        if cid not in refs or len(refs) != len(set(refs)):
            errors.append(f"Missing self link or duplicate links {cid}")
        for link in item.findall("link"):
            ref = link.findtext("linkclipref")
            actual = (link.findtext("mediatype"), integer(link, "trackindex"), integer(link, "clipindex"))
            if ref not in items:
                errors.append(f"Dangling link {cid} -> {ref}")
            elif actual != locations[ref]:
                errors.append(f"Wrong link indices {cid} -> {ref}")
            elif set(refs) != {l.findtext("linkclipref") for l in items[ref].findall("link")}:
                errors.append(f"Nonreciprocal/incomplete links {cid} -> {ref}")
            if ref in items:
                own_file, linked_file = item.find("file"), items[ref].find("file")
                if (own_file is not None and linked_file is not None and
                        own_file.get("id") != linked_file.get("id")):
                    errors.append(f"Link joins different source files {cid} -> {ref}")
        file = item.find("file")
        definition = files.get(file.get("id")) if file is not None else None
        if definition is not None and definition.find("media/audio") is not None:
            channels = [integer(items[ref].find("sourcetrack"), "trackindex")
                        for ref in refs if ref in items and locations[ref][0] == "audio"
                        and items[ref].find("sourcetrack") is not None]
            expected = integer(definition, "media/audio/channelcount")
            if sorted(channels) != list(range(1, expected + 1)):
                errors.append(f"Missing or repeated original audio channels {cid}")
        if definition is not None and definition.find("media/video") is not None:
            video_refs = [ref for ref in refs if ref in locations and locations[ref][0] == "video"]
            if len(video_refs) != 1:
                errors.append(f"Missing or repeated original video link {cid}")
    for marker in sequence.findall("marker"):
        start, end = integer(marker, "in"), integer(marker, "out")
        if start < 0 or start > duration or (end != -1 and not start <= end <= duration):
            errors.append("Invalid marker bounds")
    return {"valid": not errors, "errors": errors, "clip_count": len(items)}
