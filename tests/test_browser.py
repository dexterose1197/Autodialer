import os
import re
import socket
import subprocess
import sys

import pytest

from test_integration import eventually

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def browser_host(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    host = subprocess.Popen(
        [sys.executable, "-m", "autodialer.launcher", "--data-dir", str(tmp_path),
         "--fixture-transcripts", "--no-browser", "--lan", "--port", str(port)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        line = host.stdout.readline()
        code = re.search(r"#code=([\w-]+)", line).group(1)
        from urllib.error import URLError
        from urllib.request import urlopen

        url = f"http://127.0.0.1:{port}/"

        def is_ready():
            try:
                with urlopen(url, timeout=1) as response:
                    return response.status == 200
            except URLError:
                return False

        eventually(is_ready, timeout=15)
        yield url, code
    finally:
        host.terminate()
        host.communicate(timeout=10)


def test_android_viewport_pairs_and_completes_a_demo(browser_host, tmp_path):
    url, code = browser_host
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.getenv("AUTODIALER_TEST_CHROMIUM"))
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True,
                                has_touch=True, accept_downloads=True)
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.goto(url)
        page.get_by_label("Session access code").fill(code)
        page.get_by_role("button", name="Connect", exact=True).click()
        playwright.expect(page.get_by_role("heading", name="Verification jobs")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth")
        page.locator("#demo").click()
        page.get_by_role("button", name="Review", exact=True).click()
        playwright.expect(page.locator("#review-audio")).to_be_visible()
        page.get_by_label("Final result").fill("Manually verified")
        page.get_by_label("Review note").fill("Checked from the mobile workflow.")
        page.get_by_role("button", name="Save review").click()
        playwright.expect(page.get_by_text("Review saved.", exact=True)).to_be_visible()
        with page.expect_download() as event:
            page.get_by_role("button", name="Export", exact=True).click()
        assert event.value.suggested_filename == "autodialer-1.csv"
        export_path = tmp_path / "export.csv"
        event.value.save_as(export_path)
        assert "Checked from the mobile workflow." in export_path.read_text(encoding="utf-8-sig")
        page.get_by_role("button", name="Workflow", exact=True).click()
        page.get_by_label("Workflow name").fill("Updated Android workflow")
        page.get_by_label("Keys to press").fill("5")
        page.get_by_role("button", name="Save workflow").click()
        playwright.expect(page.get_by_text("Workflow saved for future imports.")).to_be_visible()
        page.get_by_role("button", name="Jobs", exact=True).click()
        page.get_by_role("button", name="Import destinations", exact=True).click()
        page.get_by_label("Destination file").set_input_files({
            "name": "test.txt", "mimeType": "text/plain", "buffer": b"+12025550111\n",
        })
        page.get_by_role("button", name="Import file").click()
        page.get_by_role("button", name="Resume", exact=True).click()
        playwright.expect(page.get_by_text("The configured digits did not reach verification.")).to_be_visible()
        page.get_by_role("button", name="Audit log").click()
        playwright.expect(page.get_by_text("Review saved", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth")
        assert not page_errors


def test_standalone_android_demo_runs_offline(tmp_path):
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "packaging" / "build_android_demo.py"
    demo = tmp_path / "demo.html"
    subprocess.run([sys.executable, str(script), "--output", str(demo)], check=True)
    with playwright.sync_playwright() as engine:
        browser = engine.chromium.launch(executable_path=os.getenv("AUTODIALER_TEST_CHROMIUM"))
        page = browser.new_page(viewport={"width": 390, "height": 844}, offline=True,
                                is_mobile=True, has_touch=True, accept_downloads=True)
        page.set_content(demo.read_text(encoding="utf-8"))
        page.get_by_role("button", name="Run demo").click()
        page.get_by_role("button", name="Review", exact=True).click()
        playwright.expect(page.locator("audio")).to_be_visible()
        page.get_by_label("Final result").fill("Synthetic review")
        page.get_by_role("button", name="Save review").click()
        playwright.expect(page.get_by_text("Review saved.")).to_be_visible()
        with page.expect_download() as event:
            page.get_by_role("button", name="Export CSV").click()
        export_path = tmp_path / "walkthrough.csv"
        event.value.save_as(export_path)
        assert "Synthetic review" in export_path.read_text(encoding="utf-8-sig")
        assert page.evaluate("document.documentElement.scrollWidth === window.innerWidth")
