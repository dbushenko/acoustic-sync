"""Local UI security and job lifecycle tests without an external service."""
import json
from pathlib import Path
import time
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from acoustic_sync.web.app import create_app
from acoustic_sync.web.jobs import JobManager
import acoustic_sync.web.jobs as jobs_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(JobManager, "_schedule", lambda self: None)
    app = create_app(tmp_path / "state")
    with TestClient(app, base_url="http://127.0.0.1:8765") as value:
        yield value


def headers(client):
    return {"X-Session-Token": client.get("/api/session").json()["token"], "Origin": "http://127.0.0.1:8765"}


def request_values(tmp_path):
    source = tmp_path/"input"
    source.mkdir(exist_ok=True)
    return {"input_dir":str(source),"output_xml":str(tmp_path/"export"/"timeline.xml"),
            "fps":"30000/1001","confidence_threshold":70,"workers":2}


def test_local_ui_and_required_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'charset="utf-8"' in response.text
    assert "0-100 threshold" in response.text
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("extra", [{"Host":"attacker.example"}, {"Host":"127.0.0.1:1234"},
                                    {"Origin":"https://evil.example"}, {"Sec-Fetch-Site":"cross-site"}])
def test_rejects_foreign_hosts_origins_and_ports(client, extra):
    assert client.get("/api/jobs", headers=extra).status_code == 403


def test_modifications_require_session_token(client, tmp_path):
    values = request_values(tmp_path)
    assert client.post("/api/jobs", json=values).status_code == 403
    auth = headers(client)
    response = client.post("/api/jobs", json=values, headers=auth)
    assert response.status_code == 201
    assert response.json()["fps"] == "30000/1001"
    assert response.json()["status"] == "queued"
    assert client.post("/api/jobs", json=values, headers=auth).status_code == 409


def test_folder_picker_requires_token_and_filters_files(client, tmp_path):
    (tmp_path / "Footage").mkdir()
    (tmp_path / "timeline.xml").write_text("<xmeml/>")
    (tmp_path / "recording.wav").write_bytes(b"audio")
    values = {"path": str(tmp_path)}
    assert client.post("/api/filesystem/browse", json=values).status_code == 403
    auth = headers(client)
    response = client.post("/api/filesystem/browse", json=values, headers=auth)
    assert response.status_code == 200
    entries = response.json()["entries"]
    assert "Footage" in [entry["name"] for entry in entries]
    assert all(entry["kind"] == "directory" for entry in entries)
    values["show_xml"] = True
    entries = client.post("/api/filesystem/browse", json=values, headers=auth).json()["entries"]
    assert [entry["name"] for entry in entries if entry["kind"] == "file"] == ["timeline.xml"]


def test_folder_picker_roots_and_initial_missing_path(client, tmp_path):
    auth = headers(client)
    roots = client.post("/api/filesystem/browse", json={}, headers=auth).json()
    assert roots["path"] is None
    assert roots["entries"]
    assert all(Path(entry["path"]).is_absolute() for entry in roots["entries"])
    missing = tmp_path / "new-export" / "timeline.xml"
    values = {"path": str(missing), "initial": True}
    response = client.post("/api/filesystem/browse", json=values, headers=auth)
    assert response.json()["path"] == str(tmp_path.resolve())
    assert not missing.parent.exists()
    values["initial"] = False
    assert client.post("/api/filesystem/browse", json=values, headers=auth).status_code == 404
    assert client.post("/api/filesystem/browse", json={"path": "relative"}, headers=auth).status_code == 422


@pytest.mark.parametrize("fps", ["0", "nan", "1/0", "29.5", "300", True])
def test_invalid_frame_rates_rejected_at_api(client, tmp_path, fps):
    values = request_values(tmp_path)
    values["fps"] = fps
    assert client.post("/api/jobs", json=values, headers=headers(client)).status_code == 422


def test_queue_cancel_and_not_found(client, tmp_path):
    auth = headers(client)
    job = client.post("/api/jobs", json=request_values(tmp_path), headers=auth).json()
    response = client.post(f"/api/jobs/{job['id']}/cancel", headers=auth)
    assert response.json()["status"] == "cancelled"
    assert (client.app.state.manager.root/job["id"]/"cancel").exists()
    assert client.get("/api/jobs/absent").status_code == 404


def test_artifacts_are_an_allowlist(client, tmp_path):
    job = client.post("/api/jobs", json=request_values(tmp_path), headers=headers(client)).json()
    manager = client.app.state.manager
    directory = manager.root/job["id"]/"artifacts"
    directory.mkdir()
    (directory/"timeline.xml").write_text("<xmeml/>")
    manager.jobs[job["id"]].update(status="completed", artifacts=["timeline.xml"])
    assert client.get(f"/api/jobs/{job['id']}/artifacts/timeline.xml").text == "<xmeml/>"
    assert client.get(f"/api/jobs/{job['id']}/artifacts/status.json").status_code == 404
    assert client.get("/static/jobs.py").status_code == 404


def test_restart_marks_unfinished_job_interrupted(tmp_path, monkeypatch):
    monkeypatch.setattr(JobManager, "_schedule", lambda self: None)
    manager = JobManager(tmp_path/"state")
    job = manager.submit(request_values(tmp_path))
    restarted = JobManager(manager.root)
    restarted.start()
    try:
        assert restarted.snapshot(job["id"])["status"] == "interrupted"
    finally:
        restarted.stop()


def test_queue_capacity_is_bounded(tmp_path):
    manager = JobManager(tmp_path/"state", capacity=1)
    values = request_values(tmp_path)
    manager.submit(values)
    values["output_xml"] = str(tmp_path/"another"/"timeline.xml")
    with pytest.raises(OverflowError):
        manager.submit(values)


@pytest.mark.parametrize("returncode,status", [(0,"completed"),(2,"partial"),(1,"failed"),(130,"cancelled")])
def test_subprocess_exit_codes_and_download_collection(tmp_path, monkeypatch, returncode, status):
    manager = JobManager(tmp_path/"state")
    values = request_values(tmp_path)
    submitted = manager.submit(values)
    job = manager.jobs[submitted["id"]]
    job.update(status="running", started_at=time.time()-1)
    class Process:
        def __init__(self, args, **kwargs):
            self.returncode = returncode
            assert args[args.index("--fps")+1] == "30000/1001"
            Path(values["output_xml"]).write_text("<xmeml/>")
        def poll(self):
            return self.returncode
    monkeypatch.setattr(jobs_module.subprocess, "Popen", Process)
    manager._run(job)
    assert job["status"] == status
    assert "timeline.xml" in job["artifacts"]
    assert "run.log" in job["artifacts"]
