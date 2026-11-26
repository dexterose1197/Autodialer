"""Build the offline x64 Linux release and its checksum for the pilot."""

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = Path(__file__).with_name("requirements-linux-x64.txt")


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def release_permissions(member):
    member.mode = 0o755 if member.isdir() else 0o644
    return member


def build(version, output, model_dir):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="autodialer-bundle-") as temporary:
        stage = Path(temporary)
        wheelhouse = stage / "wheelhouse"
        wheelhouse.mkdir()
        pip = [sys.executable, "-m", "pip", "--disable-pip-version-check"]
        subprocess.run([*pip, "download", "--only-binary=:all:", "--no-deps",
                        "--require-hashes", "-r", str(LOCK), "-d", str(wheelhouse)], check=True)
        subprocess.run([*pip, "wheel", "--no-deps", "-w", str(wheelhouse), str(ROOT)], check=True)
        shutil.copyfile(LOCK, stage / "requirements.lock")
        if model_dir is None:
            model_dir = stage / "download"
            subprocess.run([sys.executable, str(ROOT / "packaging" / "fetch_model.py"), str(model_dir)],
                           env={**os.environ, "HF_HUB_DISABLE_XET": "1"}, check=True)
        model = stage / "model"
        model.mkdir()
        checksums = ROOT / "packaging" / "model-SHA256SUMS.txt"
        for line in checksums.read_text(encoding="ascii").splitlines():
            expected, filename = line.split("  ", 1)
            if digest(model_dir / filename) != expected:
                raise ValueError(f"Unexpected checksum for model file {filename}.")
            shutil.copyfile(model_dir / filename, model / filename)
        shutil.copyfile(checksums, model / checksums.name)
        (stage / "release.txt").write_text(version + "\n", encoding="ascii")
        archive = output / f"{version}.tar.gz"
        with tarfile.open(archive, "w:gz", compresslevel=3) as bundle:
            for filename in ("wheelhouse", "requirements.lock", "model", "release.txt"):
                bundle.add(stage / filename, arcname=filename, filter=release_permissions)
        (output / f"{version}.sha256").write_text(digest(archive) + "\n", encoding="ascii")
        print(archive)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="Full lowercase Git commit SHA.")
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "ec2")
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.version):
        parser.error("Expected a full lowercase Git commit SHA.")
    if sys.version_info[:2] != (3, 12) or sys.platform != "linux" or os.uname().machine != "x86_64":
        parser.error("Build on x86-64 Linux with Python 3.12.")
    build(args.version, args.output, args.model_dir)
