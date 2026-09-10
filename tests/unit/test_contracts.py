"""JSON contract, configuration, atomic write, and owned cleanup regressions."""
from copy import deepcopy
import json

import pytest
from jsonschema import ValidationError

from acoustic_sync.config import Config
from acoustic_sync.contracts import atomic_json, read_json, validate
from acoustic_sync.pipeline import OutputLock, cleanup_temp


def media(mid):
    return {"id": mid, "file_path": f"/media/{mid}.wav", "relative_path": f"{mid}.wav",
            "kind": "audio", "duration_seconds": 8, "duration": "8", "video": None,
            "audio_streams": [], "status": "error"}


@pytest.fixture
def sync_map():
    return {"schema_version": "1.0", "sample_rate": 22050,
            "media": [media(mid) for mid in "abc"],
            "groups": [{"id": "g1", "reference_id": "a", "members": [
                {"media_id": "a", "offset_samples": 0, "confidence": 100},
                {"media_id": "b", "offset_samples": 22050, "confidence": 90}]}],
            "unmatched_clips": [{"media_id": "c", "file_path": "/media/c.wav", "confidence": 0, "reason": "no match"}],
            "matches": [], "master_tracks": ["a"], "aligned_clips": []}


def test_valid_sync_map_roundtrip_does_not_mutate(tmp_path, sync_map):
    before = deepcopy(sync_map)
    assert validate(sync_map, "sync_map") is sync_map
    path = tmp_path / "同步.json"
    atomic_json(path, sync_map)
    assert read_json(path, "sync_map") == before
    assert sync_map == before


@pytest.mark.parametrize("case", ["media", "within_group", "between_groups", "group_and_unmatched", "unmatched", "missing", "unknown", "reference"])
def test_rejects_duplicate_missing_unknown_assignments(sync_map, case):
    group = sync_map["groups"][0]
    if case == "media":
        sync_map["media"].append(deepcopy(sync_map["media"][0]))
    elif case == "within_group":
        group["members"].append(deepcopy(group["members"][0]))
    elif case == "between_groups":
        other = deepcopy(group)
        other["id"] = "g2"
        sync_map["groups"].append(other)
    elif case == "group_and_unmatched":
        sync_map["unmatched_clips"][0]["media_id"] = "a"
    elif case == "unmatched":
        sync_map["unmatched_clips"].append(deepcopy(sync_map["unmatched_clips"][0]))
    elif case == "missing":
        sync_map["unmatched_clips"] = []
    elif case == "unknown":
        sync_map["unmatched_clips"][0]["media_id"] = "unknown"
    else:
        group["reference_id"] = "c"
    with pytest.raises(ValueError):
        validate(sync_map, "sync_map")


@pytest.mark.parametrize("field,value", [("schema_version", "2.0"), ("sample_rate", 48000)])
def test_contract_rejects_unknown_version_and_rate(sync_map, field, value):
    sync_map[field] = value
    with pytest.raises(ValidationError):
        validate(sync_map, "sync_map")


@pytest.mark.parametrize("value", [-1, 1.5, True])
def test_offsets_are_nonnegative_integers(sync_map, value):
    sync_map["groups"][0]["members"][1]["offset_samples"] = value
    with pytest.raises(ValidationError):
        validate(sync_map, "sync_map")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_rejects_invalid_numeric_duration(sync_map, value):
    sync_map["media"][0]["duration_seconds"] = value
    with pytest.raises((ValueError, ValidationError)):
        validate(sync_map, "sync_map")


@pytest.mark.parametrize("location", ["group", "unmatched"])
def test_rejects_nan_confidence(sync_map, location):
    target = sync_map["groups"][0]["members"][0] if location == "group" else sync_map["unmatched_clips"][0]
    target["confidence"] = float("nan")
    with pytest.raises((ValueError, ValidationError)):
        validate(sync_map, "sync_map")


def test_manifest_rejects_duplicate_media_ids():
    value = {"schema_version": "1.0", "sample_rate": 22050, "input_dir": "/input",
             "temp_dir": "/tmp", "media": [media("a"), media("a")]}
    with pytest.raises(ValueError, match="duplicate media"):
        validate(value, "media_manifest")


def test_atomic_json_unicode_and_replace(tmp_path):
    path = tmp_path / "nested" / "данные.json"
    atomic_json(path, {"name": "录音 & звук"})
    assert "录音 & звук" in path.read_text(encoding="utf-8")
    atomic_json(path, {"new": 1})
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": 1}
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), object()])
def test_failed_serialization_preserves_output_and_removes_partial_file(tmp_path, bad):
    path = tmp_path / "data.json"
    path.write_bytes(b"original")
    with pytest.raises((ValueError, TypeError)):
        atomic_json(path, {"bad": bad})
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("field", ["timeout", "min_overlap"])
@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_config_rejects_nonfinite_runtime_limits(field, value):
    with pytest.raises(ValueError):
        Config(**{field: value})


def owned(parent, run_id="run1"):
    target = parent / "tmp_audio" / run_id
    target.mkdir(parents=True)
    atomic_json(target / ".owner.json", {"purpose": "acoustic-sync", "run_id": run_id})
    (target / "reference.wav").write_bytes(b"audio")
    return target


def test_cleanup_removes_only_owned_run_and_keeps_siblings(tmp_path):
    target = owned(tmp_path)
    sibling = owned(tmp_path, "run2")
    cleanup_temp(target, "run1")
    assert not target.exists()
    assert (sibling / "reference.wav").read_bytes() == b"audio"
    cleanup_temp(sibling, "run2")
    assert not sibling.parent.exists()
    cleanup_temp(sibling, "run2")


@pytest.mark.parametrize("case", ["missing_marker", "wrong_owner", "wrong_id", "wrong_parent"])
def test_cleanup_refuses_unowned_targets(tmp_path, case):
    target = owned(tmp_path)
    if case == "missing_marker":
        (target / ".owner.json").unlink()
    elif case == "wrong_owner":
        atomic_json(target / ".owner.json", {"purpose": "other", "run_id": "run1"})
    elif case == "wrong_parent":
        destination = tmp_path / "user_data" / "run1"
        destination.parent.mkdir()
        target.rename(destination)
        target = destination
    with pytest.raises(ValueError):
        cleanup_temp(target, "other" if case == "wrong_id" else "run1")
    assert (target / "reference.wav").exists()


def test_cleanup_refuses_symlink_target(tmp_path):
    target = owned(tmp_path / "real")
    alias = tmp_path / "alias" / "tmp_audio" / "run1"
    alias.parent.mkdir(parents=True)
    try:
        alias.symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symlink creation unavailable: {error}")
    with pytest.raises(ValueError):
        cleanup_temp(alias, "run1")
    assert (target / "reference.wav").exists()


def test_cleanup_refuses_symlinked_parent_outside_owned_tree(tmp_path):
    # A stale/copied marker must not authorize deleting through a redirected parent.
    target = tmp_path / "user_data" / "run1"
    target.mkdir(parents=True)
    atomic_json(target / ".owner.json", {"purpose": "acoustic-sync", "run_id": "run1"})
    (target / "important.wav").write_bytes(b"keep")
    alias_parent = tmp_path / "tmp_audio"
    try:
        alias_parent.symlink_to(target.parent, target_is_directory=True)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symlink creation unavailable: {error}")
    with pytest.raises(ValueError):
        cleanup_temp(alias_parent / "run1", "run1")
    assert (target / "important.wav").read_bytes() == b"keep"


def test_output_lock_rejects_second_owner_and_releases_after_exception(tmp_path):
    with pytest.raises(RuntimeError, match="job failed"):
        with OutputLock(tmp_path):
            with pytest.raises(ValueError, match="locked"):
                with OutputLock(tmp_path):
                    pytest.fail("Second owner acquired the lock")
            raise RuntimeError("job failed")
    assert not (tmp_path / ".acoustic-sync.lock").exists()
    with OutputLock(tmp_path):
        assert (tmp_path / ".acoustic-sync.lock").exists()


@pytest.mark.parametrize("field,value", [("workers", True), ("workers", 1.5),
                                        ("sample_rate", 22050.0), ("timeout", True),
                                        ("min_overlap", True), ("keep_temp", "false")])
def test_config_rejects_wrong_python_types(field, value):
    with pytest.raises((TypeError, ValueError)):
        Config(**{field: value})


@pytest.mark.parametrize("field", ["sample_rate", "offset_samples"])
def test_read_json_rejects_float_values_where_consumers_require_python_int(tmp_path, sync_map, field):
    # JSON Schema's mathematical integer type accepts 0.0, but range() and the
    # timeline exporter require actual Python ints. The boundary must agree.
    if field == "sample_rate":
        sync_map[field] = 22050.0
    else:
        sync_map["groups"][0]["members"][0][field] = 0.0
    path = tmp_path / "sync.json"
    atomic_json(path, sync_map)
    with pytest.raises((ValueError, ValidationError)):
        read_json(path, "sync_map")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "N/A", "-1", "1/0"])
def test_contract_rejects_invalid_playable_string_duration(sync_map, bad):
    sync_map["media"][0].update(status="ready", duration=bad, audio_streams=[
        {"index": 0, "channels": 1, "sample_rate": 48000, "start_time": "0", "duration": "8"}])
    with pytest.raises((ValueError, ValidationError)):
        validate(sync_map, "sync_map")


def test_contract_requires_video_metadata_for_playable_video(sync_map):
    sync_map["media"][0].update(kind="video", status="no_audio", video={})
    with pytest.raises((ValueError, ValidationError)):
        validate(sync_map, "sync_map")


def test_contract_rejects_duplicate_group_ids_with_disjoint_members(sync_map):
    sync_map["media"].append(media("d"))
    sync_map["unmatched_clips"] = []
    other = deepcopy(sync_map["groups"][0])
    other["reference_id"] = "c"
    for member, mid in zip(other["members"], "cd"):
        member["media_id"] = mid
    sync_map["groups"].append(other)
    with pytest.raises((ValueError, ValidationError)):
        validate(sync_map, "sync_map")


@pytest.mark.parametrize("defect", ["missing_stream_index", "wrong_rate", "unknown_stream"])
def test_manifest_reference_matches_declared_audio_stream_and_rate(defect):
    source = media("a")
    source.update(status="ready", audio_streams=[{"index": 2, "channels": 1, "sample_rate": 48000,
                                                 "start_time": "0", "duration": "8"}])
    ref = {"id": "a:2", "stream_index": 2, "wav_path": "/tmp/ref.wav",
           "sample_rate": 22050, "origin_samples": 0}
    if defect == "missing_stream_index":
        del ref["stream_index"]
    elif defect == "wrong_rate":
        ref["sample_rate"] = 11025
    else:
        ref["stream_index"] = 99
    source["references"] = [ref]
    document = {"schema_version": "1.0", "sample_rate": 22050, "input_dir": "/media",
                "temp_dir": "/tmp", "media": [source]}
    with pytest.raises((ValueError, ValidationError)):
        validate(document, "media_manifest")


@pytest.mark.parametrize("target", ["source", "manifest"])
def test_match_refuses_to_overwrite_source_or_input_manifest(tmp_path, target):
    from acoustic_sync.matching.engine import match
    source_path = tmp_path / "original.wav"
    source_path.write_bytes(b"original media")
    source = media("a")
    source.update(file_path=str(source_path), status="extraction_failed", audio_streams=[
        {"index": 0, "channels": 1, "sample_rate": 48000, "start_time": "0", "duration": "8"}])
    manifest = tmp_path / "manifest.json"
    atomic_json(manifest, {"schema_version": "1.0", "sample_rate": 22050,
                          "input_dir": str(tmp_path), "temp_dir": str(tmp_path / "refs"), "media": [source]})
    output = source_path if target == "source" else manifest
    before = output.read_bytes()
    with pytest.raises(ValueError):
        match(manifest, output, Config(workers=1))
    assert output.read_bytes() == before


def test_export_refuses_to_overwrite_original_source(tmp_path):
    from acoustic_sync.timeline import export_xml
    source_path = tmp_path / "original.wav"
    source_path.write_bytes(b"original media")
    source = media("a")
    source.update(file_path=str(source_path), status="extraction_failed", audio_streams=[
        {"index": 0, "channels": 1, "sample_rate": 48000, "start_time": "0", "duration": "8", "depth": 16}])
    document = {"schema_version": "1.0", "sample_rate": 22050, "media": [source],
                "groups": [], "matches": [], "master_tracks": [], "aligned_clips": [],
                "unmatched_clips": [{"media_id": "a", "file_path": str(source_path), "confidence": 0, "reason": "no match"}]}
    with pytest.raises(ValueError):
        export_xml(document, source_path)
    assert source_path.read_bytes() == b"original media"
