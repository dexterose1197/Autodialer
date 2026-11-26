import os
import shutil
import subprocess
from pathlib import Path

import pytest

CONTROL = Path(__file__).resolve().parents[1] / "deploy" / "ec2" / "pilot-control.sh"


@pytest.mark.skipif(
    not all(shutil.which(program) for program in ("bash", "flock", "mv")),
    reason="Linux pilot controller requires Bash and flock.",
)
def test_pilot_activation_automatically_recovers_and_can_roll_back(tmp_path):
    releases = tmp_path / "releases"
    versions = [digit * 40 for digit in "abc"]
    for version in versions:
        release = releases / version
        release.mkdir(parents=True)
        (release / "ready").touch()
    (releases / versions[2] / "offline").touch()
    server = tmp_path / "server.env"
    server.write_text("PILOT_HOST=pilot.example.ts.net\n")
    config = tmp_path / "stack.env"
    config.write_text(f'PILOT_ROOT="{tmp_path}"\nPILOT_SERVER_ENV="{server}"\n')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for program, body in {
        "systemctl": "exit 0",
        "journalctl": "exit 0",
        "sleep": "exit 0",
        "curl": (
            'if [[ -f "$MOCK_PILOT_ROOT/current/offline" ]]; then exit 1; fi\n'
            'echo \'{"pilot":true,"engine":"Faster Whisper","provider":"Simulated IVR"}\''
        ),
    }.items():
        executable = bin_dir / program
        executable.write_text(f"#!/bin/bash\n{body}\n")
        executable.chmod(0o755)

    def run(*arguments):
        return subprocess.run(
            ["bash", str(CONTROL), *arguments], capture_output=True, text=True,
            env={**os.environ, "MOCK_PILOT_ROOT": str(tmp_path),
                 "AUTODIALER_PILOT_CONFIG": str(config), "PATH": f"{bin_dir}:{os.environ['PATH']}"},
            timeout=10,
        )

    # Deploy the unhealthy release before a cleanup can prune the test fixture.
    (tmp_path / "current").symlink_to(releases / versions[0])
    failed = run("deploy", versions[2])
    assert failed.returncode != 0
    assert "Restored the previous release" in failed.stderr
    assert (tmp_path / "current").resolve() == releases / versions[0]

    deployed = run("deploy", versions[1])
    assert deployed.returncode == 0, deployed.stderr
    assert (tmp_path / "current").resolve() == releases / versions[1]
    assert (tmp_path / "previous").resolve() == releases / versions[0]

    restored = run("rollback")
    assert restored.returncode == 0, restored.stderr
    assert (tmp_path / "current").resolve() == releases / versions[0]
    assert (tmp_path / "previous").resolve() == releases / versions[1]
