"""Build a self-contained synthetic browser walkthrough from bundled fixtures."""

import argparse
import base64
import csv
import html
import io
import json
from pathlib import Path
from urllib.parse import quote

from autodialer.app import DEMO_ROWS, STATIC
from autodialer.interchange import spreadsheet_text
from autodialer.verification import CATALOG, DEFAULT_WORKFLOW, FIXTURES, classify

ROOT = Path(__file__).resolve().parent.parent


def completed_record(record):
    destination = html.escape(record["destination"])
    label = html.escape(record["label"])
    transcript = html.escape(record["transcript"])
    return f"""<article class="record">
            <div class="record-title">
              <strong>{destination}</strong>
              <span class="badge done">Completed</span>
              <strong>{label}</strong>
            </div>
            <p>{transcript}</p>
          </article>"""


def sample_csv(records):
    output = io.StringIO()
    writer = csv.writer(output)
    columns = ("destination", "transcript", "label", "note")
    writer.writerow((*columns[:3], "review_note"))
    writer.writerows([spreadsheet_text(record[column]) for column in columns] for record in records)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "AutoDialer-Android-demo.html")
    args = parser.parse_args()
    records = [
        {"destination": destination, "transcript": CATALOG[scenario],
         "label": classify(DEFAULT_WORKFLOW, CATALOG[scenario])[0] or "", "note": ""}
        for destination, scenario in DEMO_ROWS
    ]
    review_record = next(record for record in records if not record["label"])
    sample = sample_csv(records)
    template = Path(__file__).with_name("android-demo.html").read_text(encoding="utf-8")
    demo = (
        template.replace("__STYLES__", (STATIC / "style.css").read_text(encoding="utf-8"))
        .replace("__COMPLETED_RECORDS__", "\n          ".join(
            completed_record(record) for record in records if record["label"]
        ))
        .replace("__REVIEW_DESTINATION__", html.escape(review_record["destination"]))
        .replace("__REVIEW_TRANSCRIPT__", html.escape(review_record["transcript"]))
        .replace("__WAV__", base64.b64encode((FIXTURES / "ambiguous.wav").read_bytes()).decode())
        .replace("__CSV_URL__", "data:text/csv;charset=utf-8," + quote("\ufeff" + sample))
        .replace("__CSV_TEXT__", html.escape(sample))
        .replace("__RECORDS__", json.dumps(records).replace("<", "\\u003c"))
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(demo, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
