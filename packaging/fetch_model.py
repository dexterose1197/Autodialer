"""Build-time download of the exact model distributed by the Windows package."""

import argparse
import hashlib
from pathlib import Path

from huggingface_hub import snapshot_download

REPOSITORY = "Systran/faster-whisper-tiny.en"
REVISION = "0d3d19a32d3338f10357c0889762bd8d64bbdeba"
FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    target = parser.parse_args().directory
    snapshot_download(REPOSITORY, revision=REVISION, local_dir=target, allow_patterns=FILES)
    checksums = []
    for name in FILES:
        with (target / name).open("rb") as model_file:
            checksums.append(f"{hashlib.file_digest(model_file, 'sha256').hexdigest()}  {name}")
    (target / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
