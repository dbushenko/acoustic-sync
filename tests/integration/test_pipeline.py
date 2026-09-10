import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import pytest
from acoustic_sync.config import Config
from acoustic_sync.pipeline import run
from acoustic_sync.timeline import export_xml
from tests.fixtures.audio import recording, write_wav


@pytest.mark.ffmpeg
def test_end_to_end_originals_and_cleanup(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg unavailable")
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "input"
    source.mkdir()
    x = recording(12)
    master = source/"master.wav"
    write_wav(master, x)
    scratch = tmp_path/"scratch.wav"
    write_wav(scratch, x[round(2.345*22050):round(7.345*22050)])
    subprocess.run(["ffmpeg", "-v","error","-f","lavfi","-i","color=c=blue:s=160x90:r=25:d=5",
                    "-i",str(scratch),"-c:v","mpeg4","-c:a","aac","-shortest",str(source/"camera.mp4")],check=True)
    write_wav(source/"orphan.wav", recording(2, seed=777))
    report = run(source, tmp_path/"output"/"timeline.xml", Config())
    assert report["groups"] == 1
    assert report["unmatched"] == 1
    assert not (tmp_path/"tmp_audio").exists()
    sync = json.loads((tmp_path/"output"/"sync_map.json").read_text())
    export_xml(sync, tmp_path/"output"/"again.xml", "30000/1001")
    root = ET.parse(tmp_path/"output"/"again.xml")
    assert {c.findtext("name") for c in root.findall(".//sequence//clipitem")} == {"camera.mp4", "master.wav", "orphan.wav"}
    assert any("[NOT_SYNCED]" in (m.findtext("name") or "") for m in root.findall("sequence/marker"))
    assert len(list(source.glob("*"))) == 3
