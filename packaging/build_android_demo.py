"""Build a self-contained synthetic browser walkthrough from bundled fixtures."""

import argparse
import base64
import json
from pathlib import Path

from autodialer.app import DEMO_ROWS, STATIC
from autodialer.verification import CATALOG, DEFAULT_WORKFLOW, FIXTURES, classify

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "AutoDialer-Android-demo.html")
    args = parser.parse_args()
    records = [
        {"destination": destination, "transcript": CATALOG[scenario],
         "label": classify(DEFAULT_WORKFLOW, CATALOG[scenario])[0] or "", "note": ""}
        for destination, scenario in DEMO_ROWS
    ]
    template = Path(__file__).with_name("android-demo.html").read_text(encoding="utf-8")
    demo = (
        template.replace("__STYLES__", (STATIC / "style.css").read_text(encoding="utf-8"))
        .replace("__WAV__", base64.b64encode((FIXTURES / "ambiguous.wav").read_bytes()).decode())
        .replace("__RECORDS__", json.dumps(records).replace("<", "\\u003c"))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(demo, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
