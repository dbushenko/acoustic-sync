from pathlib import Path
import numpy as np
import pytest
from acoustic_sync.config import Config
from acoustic_sync.contracts import atomic_json
from acoustic_sync.matching.engine import match
from acoustic_sync.matching.refinement import refine
from acoustic_sync.matching.alignment_graph import align
from acoustic_sync.runtime import Cancellation
from tests.fixtures.audio import recording, write_wav, manifest_for


@pytest.mark.parametrize("offset", [3.375, 8.1234])
def test_fingerprint_offset_and_unrelated(tmp_path, offset):
    rate = 22050
    x = recording(22)
    start = round(offset*rate)
    paths = [tmp_path / name for name in ("master.wav", "clip.wav", "unrelated.wav", "silence.wav")]
    write_wav(paths[0], x)
    clip = x[start:start+7*rate]*0.55
    clip += np.random.default_rng(12).normal(0, 0.006, len(clip))
    write_wav(paths[1], clip)
    write_wav(paths[2], recording(5, seed=6))
    write_wav(paths[3], np.zeros(rate*3))
    manifest = tmp_path / "manifest.json"
    atomic_json(manifest, manifest_for(paths))
    result = match(manifest, tmp_path/"sync.json", Config())
    assert len(result["groups"]) == 1, result["matches"]
    members = {m["media_id"]: m["offset_samples"] for m in result["groups"][0]["members"]}
    assert abs(members["media-1"]-members["media-0"]-start) <= rate/25
    assert {m["media_id"] for m in result["unmatched_clips"]} == {"media-2", "media-3"}


def test_refinement_sign_and_audio_origin(tmp_path):
    rate = 22050
    x = recording(10)
    a, b = tmp_path/"a.wav", tmp_path/"b.wav"
    write_wav(a, x)
    write_wav(b, x[2*rate:])
    result = refine({"offset_samples": round(1.94*rate)},
                    {"wav_path": str(a), "origin_samples": 0},
                    {"wav_path": str(b), "origin_samples": round(.05*rate)}, rate, Cancellation(), .04)
    assert result["verified"]
    assert abs(result["offset_samples"]/rate-1.95) < .001


def test_drift_is_not_accepted(tmp_path):
    from scipy.signal import resample_poly
    rate = 22050
    x = recording(25)
    a, b = tmp_path/"a.wav", tmp_path/"b.wav"
    write_wav(a, x)
    write_wav(b, resample_poly(x, 1003, 1000))
    result = refine({"offset_samples": 0}, {"wav_path":str(a),"origin_samples":0},
                    {"wav_path":str(b),"origin_samples":0}, rate, Cancellation(), .04)
    assert not result["verified"]


def test_graph_chain_negative_offsets_and_cycle():
    media = [{"id": n,"kind":"audio" if n=="a" else "video","relative_path":n,"file_path":n,
              "duration_seconds":20,"audio_streams":[{}]} for n in ("a","b","c","orphan")]
    edges = [{"a_id":"a","b_id":"b","offset_samples":-100,"accepted":True,"confidence":99,"reason":"verified"},
             {"a_id":"b","b_id":"c","offset_samples":300,"accepted":True,"confidence":95,"reason":"verified"},
             {"a_id":"a","b_id":"c","offset_samples":500,"accepted":True,"confidence":80,"reason":"verified"}]
    groups, aligned, unmatched, masters = align(media, edges, 1000, .04)
    assert not edges[2]["accepted"]
    assert edges[2]["reason"] == "inconsistent_graph_cycle"
    assert len(groups) == 1
    assert {m["media_id"]:m["offset_samples"] for m in groups[0]["members"]} == {"a":100,"b":0,"c":300}
    assert next(m for m in aligned if m["media_id"]=="c")["indirect"]
    assert unmatched[0]["media_id"] == "orphan"


def test_changed_source_rejected(tmp_path):
    path = tmp_path/"a.wav"
    write_wav(path, recording(3))
    manifest = tmp_path/"m.json"
    atomic_json(manifest, manifest_for([path]))
    write_wav(path, recording(4))
    with pytest.raises(ValueError, match="changed"):
        match(manifest, tmp_path/"s.json", Config())


def test_repeated_content_remains_ambiguous(tmp_path):
    phrase = recording(5)
    paths = [tmp_path/"repeated.wav", tmp_path/"excerpt.wav"]
    write_wav(paths[0], np.tile(phrase, 4))
    write_wav(paths[1], phrase[22050:4*22050])
    atomic_json(tmp_path/"m.json", manifest_for(paths))
    result = match(tmp_path/"m.json", tmp_path/"s.json", Config())
    assert not result["groups"]
    assert len(result["unmatched_clips"]) == 2


def test_11025_alignment_across_chunk_boundary(tmp_path):
    from scipy.signal import resample_poly
    rate = 11025
    x = resample_poly(recording(36), 1, 2)
    offset = round(18.321*rate)
    paths = [tmp_path/"long.wav", tmp_path/"crossing.wav"]
    write_wav(paths[0], x, rate)
    write_wav(paths[1], x[offset:offset+10*rate], rate)
    atomic_json(tmp_path/"m.json", manifest_for(paths, rate))
    result = match(tmp_path/"m.json", tmp_path/"s.json", Config(sample_rate=rate))
    assert len(result["groups"]) == 1
    positions = {m["media_id"]:m["offset_samples"] for m in result["groups"][0]["members"]}
    assert abs(positions["media-1"]-positions["media-0"]-offset) <= rate/25
