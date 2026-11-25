import os
import subprocess
import sys
import time
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from autodialer import app as module
from autodialer.app import create_app
from autodialer.storage import MAX_ATTEMPTS, Store
from autodialer.verification import DEFAULT_WORKFLOW, FixtureTranscriber

HEADERS = {"X-AutoDialer-Client": "web"}


def client_for(database, **kwargs):
    return TestClient(create_app(database, **kwargs), base_url="http://localhost", headers=HEADERS)


def eventually(callback, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = callback()
        if result:
            return result
        time.sleep(0.025)
    pytest.fail("The expected queue condition was not reached.")


def import_records(client, data=b"+12025550101\n+12025550102\tambiguous"):
    response = client.post("/api/jobs/import?filename=sample.txt", content=data)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_demo_review_export_and_audit_persist(tmp_path):
    database = tmp_path / "data.sqlite3"
    with client_for(database) as client:
        response = client.post("/api/jobs/demo")
        assert response.status_code == 201
        job = response.json()
        assert job["synthetic"] == 1
        url = f"/api/jobs/{job['id']}"
        eventually(lambda: client.get(url).json()["review"] == 1)
        items = client.get(f"{url}/items").json()
        assert [item["label"] for item in items] == ["Confirmed", "Action required", None]
        assert client.get("/api/audio/ambiguous").content.startswith(b"RIFF")
        assert client.get("/api/audio/missing").status_code == 404
        review = f"{url}/items/{items[2]['id']}/review"
        assert client.post(review, json={"label": " ", "note": ""}).status_code == 422
        assert client.post(review, json={"label": "Valid", "note": "Bad\u0000 note"}).status_code == 422
        assert client.post(review, json={"label": "Manually checked", "note": "Fixture listened to."}).status_code == 200
        assert client.post(review, json={"label": "Overwrite"}).status_code == 409
        for fmt in ("csv", "txt", "xlsx"):
            export = client.get(f"{url}/export/{fmt}")
            assert export.status_code == 200
            assert export.headers["content-disposition"].endswith(f'.{fmt}"')
        assert b"Fixture listened to." in client.get(f"{url}/export/csv").content
    with client_for(database) as client:
        assert client.get(url).json()["done"] == 3
        assert client.get("/api/audit").json()[0]["event"] == "item.reviewed"


def test_import_is_atomic_and_revisions_are_snapshotted(tmp_path):
    with client_for(tmp_path / "data.sqlite3") as client:
        invalid = client.post("/api/jobs/import?filename=data.csv", content=b"12025550101\ninvalid")
        assert invalid.status_code == 422
        assert client.get("/api/jobs").json() == []
        job_id = import_records(client)
        assert client.get(f"/api/jobs/{job_id}").json()["paused"] == 1
        workflow = DEFAULT_WORKFLOW.model_dump()
        workflow["digits"] = "5"
        changed = client.put("/api/workflow", json=workflow).json()["revision"]
        later_job = import_records(client, b"+12025550101")
        for job in (job_id, later_job):
            assert client.post(f"/api/jobs/{job}/resume").status_code == 200
        older = eventually(lambda: next(
            (row for row in client.get(f"/api/jobs/{job_id}/items").json() if row["status"] == "done"), None
        ))
        newer = eventually(lambda: next(
            (row for row in client.get(f"/api/jobs/{later_job}/items").json() if row["status"] == "review"), None
        ))
        assert older["label"] == "Confirmed"
        assert newer["fixture"] == "menu"
        demo = client.post("/api/jobs/demo").json()
        assert demo["workflow_id"] != changed
        assert client.get("/api/workflow").json()["revision"] == changed


def test_pause_finishes_only_the_in_flight_record(tmp_path, monkeypatch):
    entered = Event()
    release = Event()

    class GatedTranscriber(FixtureTranscriber):
        def transcribe(self, recording):
            entered.set()
            if not release.wait(10):
                raise TimeoutError("Test did not release the worker.")
            return super().transcribe(recording)

    monkeypatch.setattr(module, "FixtureTranscriber", GatedTranscriber)
    with client_for(tmp_path / "data.sqlite3") as client:
        job = import_records(client)
        url = f"/api/jobs/{job}"
        assert client.post(f"{url}/resume").status_code == 200
        try:
            assert entered.wait(5)
            assert client.get(url).json()["running"] == 1
            assert client.post(f"{url}/pause").json()["paused"] == 1
        finally:
            release.set()
        assert eventually(lambda: client.get(url).json()["done"] == 1)
        assert client.get(url).json()["queued"] == 1
        assert client.post(f"{url}/resume").status_code == 200
        assert eventually(lambda: client.get(url).json()["review"] == 1)


def test_crashed_process_is_recovered_and_replayed(tmp_path):
    database = tmp_path / "data.sqlite3"
    ready = tmp_path / "claim"
    store = Store(database)
    store.initialize()
    job = store.create_job("Crash test", [("+12025550101", "confirmed")], start=True)
    holder = subprocess.Popen([sys.executable, "-c", """
from pathlib import Path
from sys import argv
from time import sleep
from filelock import FileLock
from autodialer.storage import Store
db, signal = map(Path, argv[1:])
with FileLock(str(db) + ".worker.lock"):
    item = Store(db).claim()
    signal.write_text(str(item["id"]))
    sleep(60)
""", str(database), str(ready)])
    try:
        eventually(ready.is_file)
        with pytest.raises(RuntimeError, match="already owns"):
            with client_for(database):
                pass
        assert store.jobs(job)["running"] == 1
    finally:
        holder.kill()
        holder.wait(timeout=10)
    with client_for(database) as client:
        eventually(lambda: client.get(f"/api/jobs/{job}").json()["done"] == 1)
        item = client.get(f"/api/jobs/{job}/items").json()[0]
        assert item["attempts"] == 2
        assert "item.requeued" in [entry["event"] for entry in client.get("/api/audit").json()]


def test_repeated_crashes_eventually_fail(tmp_path):
    store = Store(tmp_path / "data.sqlite3")
    store.initialize()
    job = store.create_job("Repeated crash", [("+12025550101", "confirmed")], start=True)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        assert store.claim()["attempts"] == attempt
        store.recover()
    assert store.jobs(job)["failed"] == 1
    assert store.claim() is None


def test_access_controls_require_pairing_and_client_header(tmp_path):
    with client_for(tmp_path / "data.sqlite3", access_code="private-code") as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/jobs").status_code == 401
        assert client.get("/api/audio/menu").status_code == 401
        assert client.get("/api/jobs", headers={"X-AutoDialer-Code": "invalid"}).status_code == 401
        code = {"X-AutoDialer-Code": "private-code"}
        assert client.get("/api/jobs", headers=code).status_code == 200
        assert client.post("/api/jobs/demo", headers={**code, "X-AutoDialer-Client": ""}).status_code == 403
        assert client.post("/api/jobs/demo", headers=code).status_code == 201


def test_fastapi_assets_and_loopback_host_header(tmp_path):
    with client_for(tmp_path / "data.sqlite3") as client:
        assert "AutoDialer" in client.get("/").text
        assert client.get("/assets/app.js").status_code == 200
        assert client.get("/api/status", headers={"Host": "untrusted.test"}).status_code == 400
        assert client.get("/api/status").json()["provider"] == "Simulated IVR"


@pytest.mark.skipif(not os.getenv("AUTODIALER_TEST_MODEL"), reason="Offline model path was not supplied")
def test_real_offline_transcription_completes_through_api(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    model_dir = Path(os.environ["AUTODIALER_TEST_MODEL"])
    with client_for(tmp_path / "data.sqlite3", model_dir=model_dir) as client:
        assert client.get("/api/status").json()["engine"] == "Faster Whisper"
        job = client.post("/api/jobs/demo").json()["id"]
        url = f"/api/jobs/{job}"
        eventually(lambda: client.get(url).json()["review"] == 1, timeout=90)
        results = client.get(f"{url}/items").json()
        assert [item["status"] for item in results] == ["done", "done", "review"]
        assert all(item["engine"] == "Faster Whisper" and item["transcript"] for item in results)
