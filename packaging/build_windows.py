"""Stage the Windows x64 runtime and compile a one-click NSIS installer."""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tomllib
import urllib.request
from pathlib import Path
from zipfile import ZipFile

from fetch_model import FILES, REPOSITORY, REVISION

ROOT = Path(__file__).resolve().parent.parent
PYTHON_VERSION = "3.13.17"
PYTHON_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"
)
PYTHON_SHA256 = "9e35319bffedab8b36ad44d8f377cb4f1733bcec257a0b6d04d94f01486ddb38"
VCLIBS_URL = (
    "https://download.microsoft.com/download/4/7/c/47c6134b-d61f-4024-83bd-b9c9ea951c25/"
    "Microsoft.VCLibs.x64.14.00.Desktop.appx"
)
VCLIBS_SHA256 = "b56a9101f706f9d95f815f5b7fa6efbac972e86573d378b96a07cff5540c5961"
VC_DLLS = (
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll", "vcomp140.dll",
)


def download(url, path):
    if not path.exists():
        temp = path.with_suffix(".tmp")
        with urllib.request.urlopen(url, timeout=60) as response, temp.open("wb") as output:
            shutil.copyfileobj(response, output)
        temp.replace(path)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def check_download(url, path, checksum):
    download(url, path)
    if digest(path) != checksum:
        raise ValueError(f"Unexpected checksum for {path}. Remove it before retrying.")


def stage_runtime(stage, cache):
    runtime = stage / "python"
    embed = cache / "python-win-amd64.zip"
    check_download(PYTHON_URL, embed, PYTHON_SHA256)
    with ZipFile(embed) as archive:
        archive.extractall(runtime)
    vclibs = cache / "vclibs-x64-desktop.appx"
    check_download(VCLIBS_URL, vclibs, VCLIBS_SHA256)
    with ZipFile(vclibs) as archive:
        for filename in VC_DLLS:
            archive.extract(filename, runtime)
    (runtime / "python313._pth").write_text(
        "python313.zip\n.\nLib/site-packages\nimport site\n", encoding="ascii"
    )

    packages = runtime / "Lib" / "site-packages"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile",
         "--only-binary=:all:", "--platform", "win_amd64", "--implementation", "cp",
         "--python-version", PYTHON_VERSION, "--target", str(packages),
         "--no-deps", "--require-hashes", "-r", str(ROOT / "packaging" / "requirements-win-x64.txt")],
        check=True,
    )
    shutil.rmtree(packages / "bin", ignore_errors=True)
    shutil.copytree(
        ROOT / "autodialer", packages / "autodialer", ignore=shutil.ignore_patterns("__pycache__")
    )


def stage_model(target, cache, model_path):
    target.mkdir(parents=True)
    if model_path is None:
        model_path = cache / "whisper-tiny.en"
        subprocess.run(
            [sys.executable, str(ROOT / "packaging" / "fetch_model.py"), str(model_path)],
            env={**os.environ, "HF_HUB_DISABLE_XET": "1"}, check=True,
        )
    expected = dict(line.split("  ", 1)[::-1] for line in
                    (ROOT / "packaging" / "model-SHA256SUMS.txt").read_text().splitlines())
    for name in FILES:
        source = model_path / name
        if digest(source) != expected[name]:
            raise ValueError(f"Unexpected checksum for local model file {source}.")
        shutil.copyfile(source, target / name)
    shutil.copyfile(ROOT / "packaging" / "model-SHA256SUMS.txt", target / "SHA256SUMS.txt")
    model_card = cache / "model-card.md"
    model_license = cache / "model-license.txt"
    download(f"https://huggingface.co/{REPOSITORY}/raw/{REVISION}/README.md", model_card)
    download("https://raw.githubusercontent.com/openai/whisper/v20250625/LICENSE", model_license)
    shutil.copyfile(model_card, target / "MODEL-CARD.md")
    shutil.copyfile(model_license, target / "LICENSE.txt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--makensis", default="makensis")
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    build = ROOT / "build" / "windows"
    cache = build / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    stage = build / "stage"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)

    stage_runtime(stage, cache)
    stage_model(stage / "models" / "whisper-tiny.en", cache, args.model_dir)
    for name in ("README.md", "ARCHITECTURE.md"):
        shutil.copyfile(ROOT / name, stage / name)

    output = dist / f"AutoDialer-{project['version']}-win-x64-setup.exe"
    prefix = "/" if os.name == "nt" else "-"
    subprocess.run(
        [args.makensis, f"{prefix}V2", f"{prefix}DVERSION={project['version']}",
         f"{prefix}DSTAGING={stage}", f"{prefix}DOUTPUT={output}",
         str(ROOT / "packaging" / "setup.nsi")],
        check=True,
    )
    (output.parent / (output.name + ".sha256")).write_text(
        f"{digest(output)}  {output.name}\n", encoding="ascii"
    )
    print(output)


if __name__ == "__main__":
    main()
