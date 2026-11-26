"""Generate the single-file CloudFormation template to upload in AWS."""

import argparse
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    scripts = {
        "__BOOTSTRAP_BASE64__": "bootstrap.sh",
        "__CONTROL_BASE64__": "pilot-control.sh",
    }
    template = (HERE / "stack.yml").read_text(encoding="utf-8")
    for token, file in scripts.items():
        template = template.replace(token, base64.b64encode((HERE / file).read_bytes()).decode("ascii"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(template, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
