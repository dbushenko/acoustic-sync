"""Extraction unit tests: mocked media tools, real portable subprocesses."""
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from acoustic_sync.config import Config
from acoustic_sync.extraction.scanner import EXCLUDED, scan
from acoustic_sync.runtime import Cancellation, Cancelled, run_process

probe_module = importlib.import_module("acoustic_sync.extraction.probe")
preprocess = importlib.import_module("acoustic_sync.extraction.preprocess")
runtime = importlib.import_module("acoustic_sync.runtime")


def touch(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"media")
    return path


def symlink(link, target):
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"Symlink creation unavailable: {error}")


def test_scan_recursive_unicode_duplicate_basenames_and_stable_ids(tmp_path):
    names = ["camera-a/take.MOV", "camera-b/take.MOV", "звук/录音.wav"]
    for name in names:
        touch(tmp_path, name)
    touch(tmp_path, "ignored.txt")
    before = scan(tmp_path)
    assert [m["relative_path"] for m in before] == sorted(names, key=str.casefold)
    assert len({m["id"] for m in before}) == 3
    assert all(Path(m["file_path"]).is_absolute() and m["size"] == 5 for m in before)
    touch(tmp_path, names[0]).write_bytes(b"changed")
    assert [m["id"] for m in scan(tmp_path)] == [m["id"] for m in before]


def test_scan_excludes_generated_trees_and_explicit_paths(tmp_path):
    for directory in EXCLUDED:
        touch(tmp_path, f"{directory}/hidden.wav")
    blocked = touch(tmp_path, "blocked/nested/hidden.mov").parents[1]
    file = touch(tmp_path, "omit.wav")
    touch(tmp_path, "keep.wav")
    assert [m["relative_path"] for m in scan(tmp_path, [blocked, file])] == ["keep.wav"]


def test_scan_does_not_follow_file_directory_or_cycle_symlinks(tmp_path):
    root = tmp_path / "input"
    source = touch(root, "real.wav")
    outside = touch(tmp_path, "outside/secret.wav")
    symlink(root / "alias.wav", source)
    symlink(root / "outside", outside.parent)
    symlink(root / "cycle", root)
    assert [m["relative_path"] for m in scan(root)] == ["real.wav"]


def test_scan_rejects_missing_and_non_directory_input(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan(tmp_path / "missing")
    with pytest.raises(ValueError, match="directory"):
        scan(touch(tmp_path, "file.wav"))


def test_scan_does_not_silently_drop_unreadable_subtree(tmp_path, monkeypatch):
    scanner = importlib.import_module("acoustic_sync.extraction.scanner")
    def walk(root, *, followlinks, onerror):
        onerror(PermissionError("unreadable subtree"))
        return iter(())
    monkeypatch.setattr(scanner.os, "walk", walk)
    with pytest.raises(PermissionError, match="unreadable subtree"):
        scan(tmp_path)


def video(index=0, **updates):
    return {"index": index, "codec_type": "video", "width": 1920, "height": 1080,
            "avg_frame_rate": "30000/1001", "r_frame_rate": "30000/1001",
            "duration": "8", "start_time": "10", **updates}


def audio(index=1, **updates):
    return {"index": index, "codec_type": "audio", "channels": 2,
            "sample_rate": "48000", "duration": "8", "start_time": "10.125", **updates}


def mock_probe(monkeypatch, streams, **fmt):
    data = {"streams": streams, "format": {"duration": "8", **fmt}}
    monkeypatch.setattr(probe_module, "probe_json", lambda *args: data)


def test_probe_excludes_cover_art_and_timed_thumbnails_then_selects_resolution(monkeypatch):
    mock_probe(monkeypatch, [video(0, width=9000, disposition={"attached_pic": 1}),
                            video(1, width=8000, disposition={"timed_thumbnails": 1}),
                            video(2, width=7000, avg_frame_rate="0/0", nb_frames="1"),
                            video(4), video(3), video(5, width=1280), audio(6)])
    result = probe_module.probe({"file_path": "clip.mov"}, Cancellation(), 5)
    assert result["video"]["index"] == 3
    assert result["video"]["frame_rate"] == "30000/1001"
    assert result["origin_seconds"] == "10"
    assert result["audio_streams"][0]["start_time"] == "10.125"
    assert result["status"] == "ready"


def test_probe_audio_only_uses_first_audio_origin_and_stream_duration(monkeypatch):
    mock_probe(monkeypatch, [video(disposition={"attached_pic": 1}),
                            audio(2, start_time="-0.25", duration="12"), audio(3)], duration="N/A")
    result = probe_module.probe({"file_path": "sound.m4a"}, Cancellation(), 5)
    assert result["video"] is None
    assert result["kind"] == "audio"
    assert result["origin_seconds"] == "-0.25"
    assert result["duration_seconds"] == 12


def test_probe_silent_video_retained(monkeypatch):
    mock_probe(monkeypatch, [video()])
    result = probe_module.probe({"file_path": "silent.mov"}, Cancellation(), 5)
    assert result["status"] == "no_audio"
    assert result["audio_streams"] == []


@pytest.mark.parametrize("rate", ["0/1", "-25/1"])
def test_probe_rejects_nonpositive_fallback_frame_rate(monkeypatch, rate):
    mock_probe(monkeypatch, [video(avg_frame_rate="0/0", r_frame_rate=rate)])
    with pytest.raises(ValueError):
        probe_module.probe({"file_path": "bad.mov"}, Cancellation(), 5)


def test_probe_rejects_no_playable_streams(monkeypatch):
    mock_probe(monkeypatch, [video(disposition={"attached_pic": 1})])
    with pytest.raises(ValueError, match="No playable"):
        probe_module.probe({"file_path": "cover.mp3"}, Cancellation(), 5)


@pytest.mark.parametrize("start,expected", [("10.125", 2756), ("9.75", -5512)])
def test_extract_maps_actual_stream_index_and_preserves_signed_audio_delay(tmp_path, monkeypatch, start, expected):
    root = tmp_path / "input"
    touch(root, "камера.mov")
    mock_probe(monkeypatch, [video(), audio(7, start_time=start)])
    calls = []
    def ffmpeg(args, cancel, timeout):
        calls.append(args)
        Path(args[-1]).write_bytes(b"wav")
        return ""
    monkeypatch.setattr(preprocess, "run_process", ffmpeg)
    output = tmp_path / "manifest.json"
    result = preprocess.extract(root, output, Config(workers=1), temp_dir=tmp_path / "refs")
    ref = result["media"][0]["references"][0]
    assert ref["origin_samples"] == expected
    assert ref["stream_index"] == 7
    assert calls[0][calls[0].index("-map") + 1] == "0:7"
    assert Path(ref["wav_path"]).exists()
    assert json.loads(output.read_text(encoding="utf-8")) == result


@pytest.mark.parametrize("all_fail", [False, True])
def test_extract_failed_stream_removes_partial_wav_and_preserves_source(tmp_path, monkeypatch, all_fail):
    root = tmp_path / "input"
    touch(root, "clip.mov")
    mock_probe(monkeypatch, [video(), audio(2), audio(7)])
    failed = []
    def ffmpeg(args, cancel, timeout):
        target = Path(args[-1])
        target.write_bytes(b"partial")
        if all_fail or args[args.index("-map") + 1] == "0:2":
            failed.append(target)
            raise RuntimeError("decoder failed")
        return ""
    monkeypatch.setattr(preprocess, "run_process", ffmpeg)
    result = preprocess.extract(root, tmp_path / "manifest.json", Config(workers=1), temp_dir=tmp_path / "refs")
    item = result["media"][0]
    assert item["status"] == ("extraction_failed" if all_fail else "ready")
    assert len(item["references"]) == (0 if all_fail else 1)
    assert item["audio_streams"] and item["video"]
    assert len(item["warnings"]) == len(failed)
    assert all(not path.exists() for path in failed)


def test_extract_propagates_cancellation_without_publishing_manifest(tmp_path, monkeypatch):
    root = tmp_path / "input"
    touch(root, "clip.mov")
    mock_probe(monkeypatch, [video(), audio()])
    cancel = Cancellation()
    def ffmpeg(*args):
        cancel.cancel()
        cancel.check()
    monkeypatch.setattr(preprocess, "run_process", ffmpeg)
    output = tmp_path / "manifest.json"
    with pytest.raises(Cancelled):
        preprocess.extract(root, output, Config(workers=1), cancel, temp_dir=tmp_path / "refs")
    assert not output.exists()


@pytest.mark.parametrize("mode", ["cancel", "timeout"])
def test_subprocess_is_reaped_and_pipes_closed_on_abort(monkeypatch, mode):
    cancel = Cancellation()
    children = []
    original = subprocess.Popen
    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        children.append(process)
        if mode == "cancel":
            cancel.cancel()
        return process
    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    try:
        with pytest.raises(Cancelled if mode == "cancel" else TimeoutError):
            run_process([sys.executable, "-c", "import time; time.sleep(30)"], cancel, 0.1)
        assert len(children) == 1
        assert children[0].poll() is not None
        assert children[0].stdout.closed and children[0].stderr.closed
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate()


def test_subprocess_uses_literal_arguments_and_drains_both_pipes():
    literal = "space & shell | text $(literal)"
    script = "import sys; sys.stderr.write('e'*100000); sys.stdout.write(sys.argv[1])"
    assert run_process([sys.executable, "-c", script, literal], Cancellation(), 10) == literal


def test_subprocess_nonzero_exit_reports_stderr():
    with pytest.raises(RuntimeError, match=r"failed \(7\): diagnostic"):
        run_process([sys.executable, "-c", "import sys; sys.stderr.write('diagnostic'); sys.exit(7)"], Cancellation(), 10)


def test_precancelled_process_never_spawns(monkeypatch, tmp_path):
    marker = touch(tmp_path, "cancel")
    def forbidden(*args, **kwargs):
        pytest.fail("Popen called after cancellation")
    monkeypatch.setattr(runtime.subprocess, "Popen", forbidden)
    with pytest.raises(Cancelled):
        run_process([sys.executable, "-c", "pass"], Cancellation(marker), 10)


def test_cancel_escalates_to_kill_when_terminate_does_not_exit(monkeypatch):
    cancel = Cancellation()
    events = []
    class StubbornProcess:
        def poll(self):
            return None
        def terminate(self):
            events.append("terminate")
        def kill(self):
            events.append("kill")
        def communicate(self, timeout=None):
            events.append(("communicate", timeout))
            if timeout is not None:
                raise subprocess.TimeoutExpired("test child", timeout)
            return "", ""
    def spawn(*args, **kwargs):
        cancel.cancel()
        return StubbornProcess()
    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    with pytest.raises(Cancelled):
        run_process([sys.executable, "-c", "pass"], cancel, 10)
    assert events == ["terminate", ("communicate", 3), "kill", ("communicate", None)]


@pytest.mark.parametrize("stage", ["precancel", "scan", "empty", "decode_cancel", "progress", "publish"])
def test_standalone_extract_cleans_owned_temp_on_unsuccessful_exit(tmp_path, monkeypatch, stage):
    root = tmp_path / "input"
    root.mkdir()
    if stage != "empty":
        touch(root, "clip.mov")
    refs = tmp_path / "tmp_audio" / "owned-run"
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b"previous manifest")
    mock_probe(monkeypatch, [video(), audio()])
    cancel = Cancellation()
    if stage == "precancel":
        cancel.cancel()
    if stage == "scan":
        def scan_failure(*args, **kwargs):
            raise PermissionError("injected scan failure")
        monkeypatch.setattr(preprocess, "scan", scan_failure)
    def ffmpeg(args, token, timeout):
        Path(args[-1]).write_bytes(b"partial audio")
        if stage == "decode_cancel":
            token.cancel()
            token.check()
        return ""
    monkeypatch.setattr(preprocess, "run_process", ffmpeg)
    def progress(*args):
        if stage == "progress":
            raise RuntimeError("injected callback failure")
    original_write = preprocess.atomic_json
    def write(path, value):
        if stage == "publish" and Path(path) == manifest:
            raise OSError("injected disk failure")
        return original_write(path, value)
    monkeypatch.setattr(preprocess, "atomic_json", write)
    expected = {"precancel": Cancelled, "scan": PermissionError, "empty": ValueError,
                "decode_cancel": Cancelled, "progress": RuntimeError, "publish": OSError}[stage]
    with pytest.raises(expected):
        preprocess.extract(root, manifest, Config(workers=1), cancel, progress, refs)
    assert manifest.read_bytes() == b"previous manifest"
    assert not refs.exists(), f"Owned temporary files leaked after {stage}"


@pytest.mark.parametrize("alias", [False, True], ids=["direct", "symlinked-parent"])
def test_extract_refuses_manifest_path_that_overwrites_source(tmp_path, monkeypatch, alias):
    root = tmp_path / "input"
    source = touch(root, "original.mov")
    output = source
    if alias:
        link = tmp_path / "input-alias"
        symlink(link, root)
        output = link / source.name
    mock_probe(monkeypatch, [video()])
    original = source.read_bytes()
    with pytest.raises(ValueError):
        preprocess.extract(root, output, Config(workers=1), temp_dir=tmp_path / "refs")
    assert source.read_bytes() == original


def test_extract_refuses_manifest_path_that_overwrites_ownership_marker(tmp_path, monkeypatch):
    root = tmp_path / "input"
    touch(root, "clip.mov")
    refs = tmp_path / "tmp_audio" / "run1"
    mock_probe(monkeypatch, [video()])
    with pytest.raises(ValueError):
        preprocess.extract(root, refs / ".owner.json", Config(workers=1), temp_dir=refs)


@pytest.mark.parametrize("kind", ["video", "audio"])
def test_probe_replaces_unavailable_stream_duration_with_known_format_duration(monkeypatch, kind):
    stream = video(duration="N/A") if kind == "video" else audio(duration="N/A")
    mock_probe(monkeypatch, [stream], duration="8")
    result = probe_module.probe({"file_path": "clip.mov"}, Cancellation(), 5)
    selected = result["video"] if kind == "video" else result["audio_streams"][0]
    assert float(selected["duration"]) == 8


def test_extract_honors_cancellation_after_last_progress_callback(tmp_path, monkeypatch):
    root = tmp_path / "input"
    touch(root, "silent.mov")
    mock_probe(monkeypatch, [video()])
    cancel = Cancellation()
    refs = tmp_path / "refs"
    output = tmp_path / "manifest.json"
    output.write_bytes(b"previous manifest")
    def progress(*args):
        cancel.cancel()
    with pytest.raises(Cancelled):
        preprocess.extract(root, output, Config(workers=1), cancel, progress, refs)
    assert output.read_bytes() == b"previous manifest"
    assert not refs.exists()


def test_extract_preserves_original_error_if_ownership_marker_cannot_be_written(tmp_path, monkeypatch):
    root = tmp_path / "input"
    touch(root, "clip.mov")
    def failing_write(*args, **kwargs):
        raise OSError("ownership marker disk failure")
    monkeypatch.setattr(preprocess, "atomic_json", failing_write)
    with pytest.raises(OSError, match="ownership marker disk failure"):
        preprocess.extract(root, tmp_path / "manifest.json", Config(workers=1), temp_dir=tmp_path / "refs")
