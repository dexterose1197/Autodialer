"""Install, exercise and uninstall the package on a disposable Windows test user."""

import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def poll(check, deadline):
    while time.monotonic() < deadline:
        try:
            if result := check():
                return result
        except (URLError, TimeoutError):
            pass
        time.sleep(0.4)
    raise TimeoutError("The installed application's smoke test timed out.")


def smoke(installer, temporary):
    install = temporary / "AutoDialer package"
    data = temporary / "Local data"
    log_file = temporary / "server.log"
    subprocess.run(f'"{installer}" /S /D={install}', check=True, timeout=180)
    python = install / "python" / "python.exe"
    model = install / "models" / "whisper-tiny.en"
    uninstaller = install / "Uninstall.exe"
    if not (python.is_file() and model.is_dir() and uninstaller.is_file()):
        raise RuntimeError("Installer did not create the expected files.")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    def request(path, method="GET"):
        url = f"http://127.0.0.1:{port}/api/{path}"
        with urlopen(Request(url, method=method, headers={"X-AutoDialer-Client": "web"}),
                     timeout=5) as response:
            return json.load(response)

    try:
        with log_file.open("wb") as log:
            with subprocess.Popen(
                [str(python), "-m", "autodialer.launcher", "--model-dir", str(model),
                 "--data-dir", str(data), "--port", str(port), "--no-browser"],
                cwd=install, stdout=log, stderr=subprocess.STDOUT,
                env={**os.environ, "HF_HUB_OFFLINE": "1"},
            ) as server:
                try:
                    info = poll(lambda: request("status"), time.monotonic() + 30)
                    if info["engine"] != "Faster Whisper" or info["provider"] != "Simulated IVR":
                        raise RuntimeError(f"Unexpected runtime configuration: {info}")
                    job = request("jobs/demo", "POST")
                    job_path = f"jobs/{job['id']}"
                    def queue_finished():
                        state = request(job_path)
                        return state["queued"] + state["running"] == 0

                    poll(queue_finished, time.monotonic() + 120)
                    items = request(f"{job_path}/items")
                    if [row["status"] for row in items] != ["done", "done", "review"]:
                        raise RuntimeError(f"Unexpected demo results: {items}")
                finally:
                    server.terminate()
    finally:
        if log_file.is_file():
            print(log_file.read_text(encoding="utf-8", errors="replace"))
        subprocess.run([str(uninstaller), "/S"], check=True, timeout=90)
        # The uninstaller copies itself to a temporary process before removing its files.
        poll(lambda: not uninstaller.exists(), time.monotonic() + 30)
    if not (data / "autodialer.sqlite3").is_file():
        raise RuntimeError("The expected local database was not preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installer", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="autodialer-") as directory:
        smoke(args.installer.resolve(), Path(directory))
