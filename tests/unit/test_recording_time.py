import pytest
from acoustic_sync.recording_time import recording_time, metadata_candidates


@pytest.mark.parametrize("name,day", [
    ("DJI_20260910071433_0014_D.MP4", "2026-09-10T07:14:33"),
    ("260910-071351.WAV", "2026-09-10T07:13:51"),
    ("clip_2026-09-10_07-14-33.mov", "2026-09-10T07:14:33"),
    ("clip_20260910.mov", "2026-09-10T00:00:00"),
])
def test_filename_formats(name, day):
    hint = recording_time({"file_path": name})
    assert hint["value"] == day + "+00:00"
    assert hint["source"] == "filename"
    assert hint["timezone_assumed"]


@pytest.mark.parametrize("name", ["MVI_2030.MP4", "20260230.mov", "123456-999999.wav", "take.mov"])
def test_no_invented_dates(name):
    assert recording_time({"file_path": name}) is None


def test_metadata_priority_and_fallback():
    item = {"file_path": "DJI_20260910071433.MP4", "creation_time": "2026-09-01T12:00:00+03:00"}
    assert recording_time(item)["value"] == "2026-09-01T09:00:00+00:00"
    item["creation_time"] = "invalid"
    assert recording_time(item)["source"] == "filename"
    item["creation_time"] = "2026-09-01"
    assert recording_time(item)["precision"] == "second"


def test_stream_exif_and_bwf_tags():
    tags = metadata_candidates({}, [{"index": 0, "tags": {"creation_time": "2026:09:02 11:12:13"}}])
    hint = recording_time({"recording_time_candidates": tags})
    assert hint["value"] == "2026-09-02T11:12:13+00:00"
    assert "stream:0" in hint["source"]
    tags = metadata_candidates({"origination_date": "2026-09-04", "origination_time": "15:16:17"}, [])
    assert recording_time({"recording_time_candidates": tags})["value"] == "2026-09-04T15:16:17+00:00"
