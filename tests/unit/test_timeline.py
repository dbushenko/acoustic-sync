"""Module C tests; runnable with unittest discovery or pytest, stdlib only."""

from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from acoustic_sync.timeline import export_xml, parse_frame_rate, validate_timeline


def media(mid, duration="4", *, kind="video", channels=2, fps="25", delay="0"):
    return {"id": mid, "file_path": f"E:\\Footage\\Камера & звук\\{mid} #1.mov",
            "relative_path": f"{mid}.mov", "kind": kind,
            "duration_seconds": float(duration), "duration": duration,
            "video": {"index": 0, "width": 3840, "height": 2160,
                      "frame_rate": fps, "start_time": "10", "duration": duration}
            if kind == "video" else None,
            "audio_streams": [{"index": 1 if kind == "video" else 0,
                               "channels": channels, "sample_rate": 48000, "depth": 24,
                               "start_time": str(Fraction(10) + Fraction(delay)),
                               "duration": duration}] if channels else [],
            "creation_time": "2026-09-10T07:00:00Z",
            "status": "ready" if channels else "no_audio"}


def group(gid, *members):
    return {"id": gid, "reference_id": members[0][0],
            "members": [{"media_id": mid, "offset_samples": samples, "confidence": 99}
                        for mid, samples in members]}


def sync(media_list, groups=(), orphans=()):
    return {"schema_version": "1.0", "sample_rate": 22050, "media": media_list,
            "groups": list(groups), "unmatched_clips": [
                {"media_id": mid, "file_path": "unused", "confidence": 0,
                 "reason": "no match"} for mid in orphans]}


class TimelineTests(unittest.TestCase):
    def test_parent_cli_and_pipeline_public_imports(self):
        from acoustic_sync.timeline import parse_rate as package_rate
        from acoustic_sync.timeline.rates import parse_rate
        from acoustic_sync.timeline.fcp7 import export_xml as pipeline_export
        from acoustic_sync.timeline.fcp7 import validate_timeline as pipeline_validate

        self.assertIs(package_rate, parse_rate)
        self.assertIs(parse_rate, parse_frame_rate)
        self.assertIs(pipeline_export, export_xml)
        self.assertIs(pipeline_validate, validate_timeline)
        self.assertEqual(parse_rate("29.97"), Fraction(30000, 1001))
        report = pipeline_export(sync([media("cam")]), self.path, "25", 1920, 1080)
        self.assertTrue(pipeline_validate(self.path)["valid"])
        self.assertEqual(report["duration_frames"], 100)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "timeline.xml"

    def export(self, data, **kwargs):
        report = export_xml(data, self.path, **kwargs)
        self.assertTrue(report["validation"]["valid"], report["validation"])
        self.assertTrue(validate_timeline(self.path)["valid"])
        json.dumps(report)
        return ET.parse(self.path).getroot(), report

    def test_basic_source_metadata_and_paths(self):
        source = media("cam")
        root, report = self.export(sync([source], [group("take", ("cam", 0))]))
        self.assertEqual(report["fps"], "25")
        self.assertEqual(report["duration_frames"], 100)
        self.assertEqual((report["width"], report["height"]), (3840, 2160))
        self.assertIn('<!DOCTYPE xmeml>', self.path.read_text(encoding="utf-8"))
        self.assertEqual(root.attrib, {"version": "4"})
        definition = next(f for f in root.iter("file") if len(f))
        url = definition.findtext("pathurl")
        self.assertTrue(url.startswith("file://localhost/E%3A/"))

        self.assertIn("%23", url)
        self.assertIn("%26", url)
        self.assertIn("%D0", url)
        self.assertEqual(definition.findtext("media/audio/channelcount"), "2")
        for clip in root.find("sequence").iter("clipitem"):
            metadata = json.loads(clip.findtext("logginginfo/lognote"))
            self.assertEqual(metadata["source"], source)
            self.assertEqual(len(clip.findall("link")), 3)
            self.assertEqual(clip.findtext("enabled"), "TRUE")

    def test_source_bins_preserve_nested_paths_and_duplicate_basenames(self):
        sources = [media("a"), media("b"), media("audio", kind="audio"), media("root")]
        for source, relative in zip(sources, ["Day 1/Camera A/take.mov",
                                              "Day 1/Camera B/take.mov",
                                              "Day 1/Звук & записи/take.wav", "root.mov"]):
            source["relative_path"] = relative
            source["file_path"] = "E:/Footage/" + relative
        root, report = self.export(sync(sources, [group("G", ("a", 0), ("b", 0))]))
        paths = {}

        def visit(children, prefix=()):
            for child in children:
                if child.tag == "bin":
                    visit(child.find("children"), prefix + (child.findtext("name"),))
                elif child.tag == "clip":
                    paths[child.get("id")] = prefix + (child.findtext("name"),)

        visit(root)
        self.assertEqual(set(paths.values()), {
            ("Source media", *s["relative_path"].split("/")) for s in sources})
        self.assertEqual(len(paths), 4)
        self.assertEqual(report["media_count"], 4)
        for item in root.findall(".//sequence//clipitem"):
            self.assertEqual(paths[item.findtext("masterclipid")][-1], item.findtext("name"))
        root.find(".//sequence//clipitem/masterclipid").text = "missing-master"
        self.assertFalse(validate_timeline(root)["valid"])

    def test_legacy_sequence_without_project_still_validates(self):
        root, _ = self.export(sync([media("cam")]))
        legacy = ET.Element("xmeml", version="4")
        legacy.append(root.find("sequence"))
        self.assertTrue(validate_timeline(legacy)["valid"])

    def test_xml_only_export_has_complete_browser_media(self):
        root, _ = self.export(sync([media("cam"), media("sound", kind="audio")]))
        self.assertIsNone(root.find("project"))
        self.assertIsNotNone(root.find("sequence"))
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [self.path])
        definitions = {f.get("id") for f in root.findall(".//file") if len(f)}
        all_ids = [c.get("id") for c in root.findall(".//clipitem")]
        self.assertEqual(len(all_ids), len(set(all_ids)))
        for master in root.findall(".//bin/children/clip"):
            items = master.findall("media/*/track/clipitem")
            self.assertTrue(items)
            local_ids = {c.get("id") for c in items}
            for item in items:
                self.assertEqual(item.findtext("start"), "-1")
                self.assertEqual(item.findtext("end"), "-1")
                self.assertIn(item.find("file").get("id"), definitions)
                self.assertEqual({l.findtext("linkclipref") for l in item.findall("link")}, local_ids)
        self.assertTrue(all(not p.text.lower().endswith((".prj", ".prproj"))
                            for p in root.findall(".//pathurl")))

    def test_invalid_relative_folder_rejected_before_publication(self):
        source = media("cam")
        source["relative_path"] = "../outside/cam.mov"
        with self.assertRaisesRegex(ValueError, "relative path"):
            export_xml(sync([source]), self.path)
        self.assertFalse(self.path.exists())
    def test_rational_rates_and_aliases(self):
        for text, expected, base in [("25", Fraction(25), "25"),
                                     ("29.97", Fraction(30000, 1001), "30"),
                                     ("30000/1001", Fraction(30000, 1001), "30"),
                                     ("23.976", Fraction(24000, 1001), "24"),
                                     ("59.94", Fraction(60000, 1001), "60")]:
            with self.subTest(fps=text):
                self.assertEqual(parse_frame_rate(text), expected)
                root, report = self.export(sync([media("cam", "3600", fps=text)]), fps=text)
                self.assertEqual(root.findtext("sequence/rate/timebase"), base)
                self.assertEqual(root.findtext("sequence/rate/ntsc"),
                                 "FALSE" if expected.denominator == 1 else "TRUE")
                ideal = 3600 * expected
                self.assertLessEqual(abs(report["duration_frames"] - ideal), Fraction(1, 2))
        for value in ("0", "-25", "nan", "1/0", "27.5", "nonsense"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_frame_rate(value)

    def test_interval_packing_touching_and_overlapping(self):
        sources = [media(mid, "2") for mid in ("a", "b", "c")]
        root, report = self.export(sync(sources, [group("g", ("a", 0),
                                        ("b", 22050), ("c", 44100))]))
        self.assertEqual(report["video_tracks"], 2)
        self.assertEqual(report["audio_tracks"], 4)
        first_track = root.findall("sequence/media/video/track")[0]
        self.assertEqual([c.findtext("start") for c in first_track.findall("clipitem")], ["0", "50"])
        self.assertEqual(report["duration_frames"], 100)

    def test_groups_gap_markers_and_orphans_last(self):
        sources = [media(mid, "1", channels=0) for mid in ("orphan", "b", "a", "unlisted")]
        root, report = self.export(sync(sources, [group("G1", ("a", 0)),
                                               group("G2", ("b", 0))], ["orphan"]))
        markers = root.findall("sequence/marker")
        self.assertEqual([m.findtext("name") for m in markers],
                         ["[RELATIVE_TIMING_UNKNOWN] G1", "[RELATIVE_TIMING_UNKNOWN] G2",
                          "[NOT_SYNCED] orphan", "[NOT_SYNCED] unlisted"])
        self.assertEqual([int(m.findtext("in")) for m in markers], [0, 75, 150, 225])
        self.assertEqual(report["duration_frames"], 250)
        self.assertEqual(report["orphan_count"], 2)
        self.assertEqual(report["video_tracks"], 1)
        self.assertEqual(report["audio_tracks"], 0)

    def test_ntsc_gap_and_exact_sample_offset(self):
        root, report = self.export(sync([media("a", "1.001", channels=0),
                                        media("b", "1.001", channels=0)],
                                       [group("a", ("a", 735735)), group("b", ("b", 0))]), fps="29.97")
        clips = root.findall("sequence/media/video/track/clipitem")
        self.assertEqual(clips[0].findtext("start"), "1000")
        self.assertEqual(int(clips[1].findtext("start")) - int(clips[0].findtext("end")), 60)

    def test_group_sort_by_earliest_valid_timestamp_then_undated_paths(self):
        a, b = media("a"), media("b")
        a["creation_time"] = "2026-09-10T10:00:00+03:00"
        b["creation_time"] = "2026-09-10T06:00:00Z"
        groups = [group("A", ("a", 0)), group("B", ("b", 0))]
        _, report = self.export(sync([a, b], groups))
        expected = ["[RELATIVE_TIMING_UNKNOWN] B", "[RELATIVE_TIMING_UNKNOWN] A"]
        self.assertEqual([m["name"] for m in report["markers"]], expected)
        for absent in (None, "invalid date", "06:00:00"):
            a["creation_time"] = absent
            _, report = self.export(sync([b, a], list(reversed(groups))))
            self.assertEqual([m["name"] for m in report["markers"]], expected)
        # Missing metadata on a non-reference member does not hide a valid date.
        a["creation_time"] = "2026-09-11T00:00:00Z"
        c = media("c")
        c["creation_time"] = None
        _, report = self.export(sync([a, b, c], [group("B", ("b", 0)),
                                                   group("A", ("a", 0), ("c", 0))]))
        self.assertEqual([m["name"] for m in report["markers"]], expected)
        # A non-reference member's earlier full timestamp controls group order.
        c["creation_time"] = "2026-09-09T12:00:00Z"
        _, report = self.export(sync([a, b, c], [group("B", ("b", 0)),
                                               group("A", ("a", 0), ("c", 0))]))
        self.assertEqual([m["name"] for m in report["markers"]], list(reversed(expected)))
        a["creation_time"], b["creation_time"] = None, "time only 10:00:00"
        _, report = self.export(sync([b, a], list(reversed(groups))))
        self.assertEqual([m["name"] for m in report["markers"]], list(reversed(expected)))

    def test_groups_and_orphans_interleave_by_recording_date(self):
        sources = [media(mid) for mid in ("early", "a", "b", "late", "unknown")]
        for source in sources:
            source["creation_time"] = None
        sources[0]["file_path"] = "E:/clips/DJI_20260901120000_01.MP4"
        sources[1]["creation_time"] = "2026-09-02T12:00:00Z"
        sources[2]["creation_time"] = "2026-09-02T12:00:01Z"
        sources[3]["file_path"] = "E:/clips/260904-120000.WAV"
        root, report = self.export(sync(sources, [group("G", ("a", 0), ("b", 22050))]))
        self.assertEqual([m["name"] for m in report["markers"]], [
            "[NOT_SYNCED] early", "[RELATIVE_TIMING_UNKNOWN] G", "[NOT_SYNCED] late", "[NOT_SYNCED] unknown"])
        self.assertEqual(report["markers"][0]["recording_time"]["source"], "filename")
        self.assertIsNone(report["markers"][-1]["recording_time"])
        starts = {json.loads(c.findtext("logginginfo/lognote"))["media_id"]: int(c.findtext("start"))
                  for c in root.findall("sequence/media/video/track/clipitem")}
        self.assertEqual(starts["b"] - starts["a"], 25)
        self.assertLess(starts["early"], starts["a"])
        self.assertLess(starts["b"], starts["late"])

    def test_orphans_reuse_their_folder_video_and_audio_tracks(self):
        sources = [media("grouped"), media("z"), media("a")]
        root, report = self.export(sync(sources, [group("G", ("grouped", 0))], ["z", "a"]))
        self.assertEqual([m["name"] for m in report["markers"]],
                         ["[RELATIVE_TIMING_UNKNOWN] G", "[NOT_SYNCED] a", "[NOT_SYNCED] z"])
        self.assertEqual((report["video_tracks"], report["audio_tracks"]), (1, 2))
        self.assertEqual((report["orphan_video_tracks"], report["orphan_audio_tracks"]), (1, 2))
        for kind, grouped_count in (("video", 1), ("audio", 2)):
            tracks = root.findall(f"sequence/media/{kind}/track")
            for index, track in enumerate(tracks):
                ids = {json.loads(c.findtext("logginginfo/lognote"))["media_id"]
                       for c in track.findall("clipitem")}
                self.assertEqual(ids, {"grouped", "a", "z"})
                for clip in track.findall("clipitem"):
                    mid = json.loads(clip.findtext("logginginfo/lognote"))["media_id"]
                    self.assertEqual(clip.findtext("name"), f"{mid} #1.mov")
        self.assertIn("RELATIVE_TIMING_UNKNOWN", root.findtext("sequence/marker/comment"))

    def test_camera_audio_precedes_standalone_audio_even_in_same_folder(self):
        sources = [media("camera"), media("recorder", kind="audio"), media("shared", kind="audio")]
        sources[0]["relative_path"] = "z-camera/camera.mov"
        sources[1]["relative_path"] = "a-recorder/recorder.wav"
        sources[2]["relative_path"] = "z-camera/shared.wav"
        root, report = self.export(sync(sources))
        ids = [{json.loads(c.findtext("logginginfo/lognote"))["media_id"]
                for c in track.findall("clipitem")}
               for track in root.findall("sequence/media/audio/track")]
        self.assertEqual(ids, [{"camera"}, {"camera"}, {"recorder"}, {"recorder"}, {"shared"}, {"shared"}])

    def test_folders_have_stable_tracks_across_groups_and_orphans(self):
        sources = [media(mid) for mid in ("a1", "a2", "b1", "b2", "a_overlap")]
        for source in sources:
            folder = "day/camera-a" if source["id"].startswith("a") else "day/camera-b"
            source["relative_path"] = f"{folder}/{source['id']}.mov"
        root, report = self.export(sync(sources, [group("G", ("a1", 0), ("a_overlap", 22050), ("b1", 0))]))
        video = root.findall("sequence/media/video/track")
        track_ids = [{json.loads(c.findtext("logginginfo/lognote"))["media_id"]
                      for c in track.findall("clipitem")} for track in video]
        self.assertEqual(track_ids, [{"a1", "a2"}, {"a_overlap"}, {"b1", "b2"}])
        self.assertEqual(report["track_folders"]["video"], [
            {"track": 1, "folder": "day/camera-a"},
            {"track": 2, "folder": "day/camera-a"},
            {"track": 3, "folder": "day/camera-b"}])
        for kind in ("video", "audio"):
            for track in root.findall(f"sequence/media/{kind}/track"):
                folders = {json.loads(c.findtext("logginginfo/lognote"))["source"]["relative_path"].rsplit("/", 1)[0]
                           for c in track.findall("clipitem")}
                self.assertEqual(len(folders), 1)

    def test_orphan_clip_names_and_marker_review_reasons(self):
        data = sync([media("grouped"), media("orphan"), media("unlisted")],
                    [group("G", ("grouped", 0))], ["orphan"])
        data["unmatched_clips"][0]["reason"] = "Ambiguous correlation: review manually"
        root, report = self.export(data)
        for item in root.find("sequence").iter("clipitem"):
            mid = json.loads(item.findtext("logginginfo/lognote"))["media_id"]
            filename = f"{mid} #1.mov"
            self.assertEqual(item.findtext("name"), filename)
        markers = {m.findtext("name"): m for m in root.findall("sequence/marker")}
        self.assertIn("[RELATIVE_TIMING_UNKNOWN] G", markers)
        self.assertIn("Ambiguous correlation: review manually",
                      markers["[NOT_SYNCED] orphan"].findtext("comment"))
        self.assertIn("Not assigned to a synchronization group",
                      markers["[NOT_SYNCED] unlisted"].findtext("comment"))
        self.assertEqual(report["markers"][1]["reason"], "Ambiguous correlation: review manually")

    def test_positive_audio_delay(self):
        root, report = self.export(sync([media("cam", delay="0.12")], [group("g", ("cam", 0))]))
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/start"), "0")
        for clip in root.findall("sequence/media/audio/track/clipitem"):
            self.assertEqual(clip.findtext("start"), "3")
            self.assertEqual(clip.findtext("in"), "0")
        self.assertEqual(report["duration_frames"], 103)

    def test_negative_audio_delay_shifts_whole_group(self):
        root, report = self.export(sync([media("a", delay="-0.2"), media("b")],
                                       [group("g", ("a", 0), ("b", 22050))]))
        video = root.findall("sequence/media/video/track/clipitem")
        self.assertEqual([c.findtext("start") for c in video], ["5", "30"])
        self.assertEqual(root.findtext("sequence/media/audio/track/clipitem/start"), "0")
        self.assertEqual(report["markers"][0]["shift_seconds"], "1/5")

    def test_all_channels_across_multiple_streams(self):
        source = media("cam", channels=2)
        source["audio_streams"].append({"index": 3, "channels": 6, "sample_rate": 96000,
                                        "depth": 32, "start_time": "10.2", "duration": "3"})
        root, report = self.export(sync([source]))
        audio = root.findall("sequence/media/audio/track/clipitem")
        self.assertEqual(len(audio), 8)
        self.assertEqual(report["audio_tracks"], 8)
        self.assertEqual(sorted(int(c.findtext("sourcetrack/trackindex")) for c in audio), list(range(1, 9)))
        for clip in root.find("sequence").iter("clipitem"):
            self.assertEqual(len(clip.findall("link")), 9)
        metadata = json.loads(audio[-1].findtext("logginginfo/lognote"))
        self.assertEqual(metadata["source"]["audio_streams"][1]["sample_rate"], 96000)
        self.assertFalse(any(c.find("samplecharacteristics") is not None for c in audio))
        stereo = root.find(".//clipitem").findall("link/groupindex")
        self.assertEqual([node.text for node in stereo], ["1", "1"])
        self.assertEqual(audio[-1].findtext("start"), "5")
        self.assertEqual(audio[-1].findtext("end"), "80")

    def test_audio_only_and_dimensions(self):
        root, report = self.export(sync([media("recorder", kind="audio")]), width=1280, height=720)
        self.assertEqual((report["width"], report["height"]), (1280, 720))
        self.assertEqual(report["video_tracks"], 0)
        self.assertEqual(root.findtext("sequence/media/audio/track/clipitem/start"), "0")
        _, default = self.export(sync([media("recorder", kind="audio")]))
        self.assertEqual((default["width"], default["height"]), (1920, 1080))

    def test_mixed_source_rates(self):
        root, _ = self.export(sync([media("cam", "4", fps="50")]), fps="25")
        clip = root.find("sequence/media/video/track/clipitem")
        self.assertEqual(clip.findtext("rate/timebase"), "50")
        self.assertEqual(clip.findtext("out"), "200")
        self.assertEqual(clip.findtext("end"), "100")

    def test_explicit_origin_and_extraction_failure_preserve_original(self):
        source = media("recorder", kind="audio")
        source.update(origin_seconds="9.8", status="extraction_failed")
        root, report = self.export(sync([source]))
        self.assertEqual(root.findtext("sequence/media/audio/track/clipitem/start"), "5")
        self.assertEqual(report["media_count"], 1)
        self.assertEqual(report["skipped"], [])

    def test_illegal_xml_characters_rejected_before_replacing_output(self):
        self.path.write_text("keep me", encoding="utf-8")
        with self.assertRaises(ValueError):
            export_xml(sync([media("a")], [group("bad\x01name", ("a", 0))]), self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "keep me")

    def test_subframe_duration_remains_visible(self):
        root, report = self.export(sync([media("cam", "0.001")]))
        self.assertEqual(report["duration_frames"], 1)
        self.assertEqual(root.findtext("sequence/media/video/track/clipitem/out"), "1")

    def test_errors_skipped_and_empty_timeline(self):
        bad = media("bad")
        bad.update(status="error", error="probe failed", video=None, audio_streams=[])
        root, report = self.export(sync([bad]))
        self.assertEqual(report["duration_frames"], 0)
        self.assertEqual(report["skipped"], [{"media_id": "bad", "reason": "probe failed"}])
        self.assertEqual(root.findall("sequence/marker"), [])
        _, report = self.export(sync([]))
        self.assertEqual(report["clip_count"], 0)

    def test_zero_duration_and_error_orphans_reported_positional_api(self):
        zero, bad, good = media("zero", "0"), media("bad", "0"), media("good")
        bad.update(status="error", error="unreadable file", video=None, audio_streams=[])
        data = sync([zero, bad, good], [], ["zero", "bad", "good"])
        report = export_xml(data, self.path, "29.97", 1280, 720)
        self.assertTrue(validate_timeline(self.path)["valid"])
        self.assertEqual(report["errors"], report["skipped"])
        self.assertEqual([e["media_id"] for e in report["errors"]], ["zero", "bad"])
        self.assertIn("zero duration", report["errors"][0]["reason"])
        self.assertEqual(report["orphan_count"], 1)
        self.assertEqual(report["media_count"], 1)
        self.assertEqual((report["width"], report["height"]), (1280, 720))

    def test_invalid_input_preserves_existing_output(self):
        good = sync([media("a")], [group("g", ("a", 0))])
        invalid = []
        for field, value in (("schema_version", "2.0"), ("sample_rate", 0)):
            data = deepcopy(good)
            data[field] = value
            invalid.append(data)
        for samples in (-1, 1.5, True):
            data = deepcopy(good)
            data["groups"][0]["members"][0]["offset_samples"] = samples
            invalid.append(data)
        data = deepcopy(good)
        data["media"].append(deepcopy(data["media"][0]))
        invalid.append(data)
        data = deepcopy(good)
        data["groups"][0]["reference_id"] = "missing"
        invalid.append(data)
        data = deepcopy(good)
        data["media"][0]["duration"] = "nan"
        invalid.append(data)
        self.path.write_text("keep me", encoding="utf-8")
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                export_xml(data, self.path)
            self.assertEqual(self.path.read_text(encoding="utf-8"), "keep me")

    def test_confidence_uses_zero_to_one_hundred_scale(self):
        for confidence in (0, 1, 50, 99.5, 100):
            with self.subTest(confidence=confidence):
                data = sync([media("a")], [group("g", ("a", 0))])
                data["groups"][0]["members"][0]["confidence"] = confidence
                self.export(data)
        for confidence in (-0.01, 100.01, "nan", "inf"):
            with self.subTest(confidence=confidence):
                data = sync([media("a")], [group("g", ("a", 0))])
                data["groups"][0]["members"][0]["confidence"] = confidence
                self.path.write_text("keep me", encoding="utf-8")
                with self.assertRaises(ValueError):
                    export_xml(data, self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), "keep me")

    def test_deterministic_and_does_not_mutate_input(self):
        data = sync([media("a"), media("b")], [group("g", ("b", 0), ("a", 22050))])
        before = deepcopy(data)
        self.export(data)
        payload = self.path.read_bytes()
        self.export(data)
        self.assertEqual(self.path.read_bytes(), payload)
        self.assertEqual(data, before)

    def test_validator_detects_corruption(self):
        root, _ = self.export(sync([media("a"), media("b")]))
        mutations = [
            lambda r: r.set("version", "5"),
            lambda r: setattr(r.find("sequence/duration"), "text", "1"),
            lambda r: setattr(r.find("sequence/rate/ntsc"), "text", "maybe"),
            lambda r: setattr(r.find(".//clipitem/enabled"), "text", "FALSE"),
            lambda r: setattr(r.find(".//clipitem/start"), "text", "-1"),
            lambda r: setattr(r.find(".//clipitem/out"), "text", "99999"),
            lambda r: setattr(r.find(".//link/linkclipref"), "text", "missing"),
            lambda r: setattr(r.find(".//link/trackindex"), "text", "999"),
            lambda r: setattr(r.find(".//file/pathurl"), "text", "https://wrong"),
            lambda r: r.find(".//file").set("id", "missing"),
            lambda r: setattr(r.find("sequence/media/audio/track/clipitem/sourcetrack/trackindex"), "text", "99"),
        ]
        for mutation in mutations:
            damaged = deepcopy(root)
            mutation(damaged)
            self.assertFalse(validate_timeline(damaged)["valid"])
        self.assertTrue(validate_timeline(ET.tostring(root, encoding="unicode"))["valid"])
        self.assertTrue(validate_timeline(ET.ElementTree(root))["valid"])
        self.assertFalse(validate_timeline("<broken")["valid"])
        self.assertFalse(validate_timeline(Path(self.tmp.name) / "missing.xml")["valid"])

    def test_validator_detects_overlap_and_missing_channels(self):
        root, _ = self.export(sync([media("a"), media("b")]))
        clips = root.findall("sequence/media/video/track/clipitem")
        clips[1].find("start").text = "10"
        self.assertTrue(any("overlap" in e for e in validate_timeline(root)["errors"]))
        root, _ = self.export(sync([media("a")]))
        audio = root.find("sequence/media/audio/track")
        audio.remove(audio.find("clipitem"))
        self.assertTrue(any("audio channels" in e for e in validate_timeline(root)["errors"]))


if __name__ == "__main__":
    unittest.main()
