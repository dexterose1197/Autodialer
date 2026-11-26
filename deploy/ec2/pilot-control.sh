#!/bin/bash
set -euo pipefail
umask 022

source "${AUTODIALER_PILOT_CONFIG:-/etc/autodialer-pilot/stack.env}"
export AWS_DEFAULT_REGION
base=${PILOT_ROOT:-/opt/autodialer-pilot}
server_env=${PILOT_SERVER_ENV:-/etc/autodialer-pilot/server.env}
unit=autodialer-pilot.service
operation=${1:?Missing operation}
version=${2:-none}
scratch=
trap 'if [[ -n "$scratch" ]]; then rm -rf -- "$scratch"; fi' EXIT

exec 9>"$base/deploy.lock"
flock -w 30 9

link_release() {
    ln -s "$2" "$base/.link-$$"
    mv -Tf "$base/.link-$$" "$base/$1"
}

health() {
    for attempt in {1..20}; do
        if curl -fsS --max-time 3 http://127.0.0.1:8765/api/status 2>/dev/null |
            python3 -c 'import json, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    sys.exit(1)
sys.exit(not (data.get("pilot") and data.get("provider") == "Simulated IVR"
              and data.get("engine") == "Faster Whisper"))'; then
            return 0
        fi
        sleep 2
    done
    journalctl -u "$unit" --no-pager -n 30 >&2
    return 1
}

activate() {
    local release=$1 old
    old=$(readlink "$base/current" || true)
    link_release current "$release"
    if systemctl restart "$unit" && health; then
        if [[ -n "$old" && "$old" != "$release" ]]; then
            link_release previous "$old"
        fi
        return 0
    fi

    echo "Release failed its health check." >&2
    if [[ -n "$old" && "$old" != "$release" ]]; then
        link_release current "$old"
        systemctl restart "$unit" && health && echo "Restored the previous release." >&2
    elif [[ -z "$old" ]]; then
        rm -f "$base/current"
        systemctl stop "$unit"
    fi
    return 1
}

pair() {
    local check login host
    check=$(tailscale status --json || true)
    if ! python3 -c 'import json, sys; sys.exit(json.load(sys.stdin).get("BackendState") != "Running")' <<<"$check"; then
        login=$(tailscale up --timeout=20s --hostname=autodialer-pilot \
            --advertise-tags=tag:autodialer-pilot 2>&1) || true
        if grep -oE 'https://login\.tailscale\.com/a/[A-Za-z0-9_-]+' <<<"$login"; then
            echo "Open this private enrollment link, authorize the device, then run pair again."
            return 0
        fi
        check=$(tailscale status --json || true)
        if ! python3 -c 'import json, sys; sys.exit(json.load(sys.stdin).get("BackendState") != "Running")' <<<"$check"; then
            printf '%s\n' "$login" >&2
            return 1
        fi
    fi
    host=$(python3 -c 'import json, sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' <<<"$check")
    [[ $host =~ ^[a-z0-9][a-z0-9.-]*\.ts\.net$ ]]
    tailscale serve --bg http://127.0.0.1:8765
    printf 'PILOT_HOST=%s\n' "$host" > "$server_env"
    if [[ -L "$base/current" ]]; then
        systemctl restart "$unit"
        health
    fi
    printf 'Android URL: https://%s/\n' "$host"
}

deploy() {
    [[ $version =~ ^[a-f0-9]{40}$ ]] || { echo "Invalid release version." >&2; return 1; }
    [[ -s "$server_env" ]] || { echo "Pair the instance with Tailscale first." >&2; return 1; }
    local release="$base/releases/$version" expected actual
    if [[ ! -f "$release/ready" ]]; then
        scratch=$(mktemp -d)
        aws s3 cp --only-show-errors "s3://$RELEASE_BUCKET/releases/$version.tar.gz" "$scratch/bundle"
        aws s3 cp --only-show-errors "s3://$RELEASE_BUCKET/releases/$version.sha256" "$scratch/checksum"
        expected=$(<"$scratch/checksum")
        actual=$(sha256sum "$scratch/bundle" | cut -d ' ' -f 1)
        [[ $expected =~ ^[a-f0-9]{64}$ && $expected == "$actual" ]] || {
            echo "Bundle checksum mismatch." >&2
            return 1
        }

        # An incomplete release is never linked as current or previous.
        rm -rf -- "$release"
        mkdir -p "$release"
        python3 - "$scratch/bundle" "$release" <<'PY'
import sys
import tarfile

with tarfile.open(sys.argv[1], "r:gz") as bundle:
    bundle.extractall(sys.argv[2], filter="data")
PY
        [[ $(<"$release/release.txt") == "$version" ]]
        (cd "$release/model" && sha256sum -c model-SHA256SUMS.txt)
        python3 -m venv "$release/venv"
        "$release/venv/bin/python" -m pip --disable-pip-version-check install --no-index --no-deps \
            --require-hashes --find-links "$release/wheelhouse" -r "$release/requirements.lock"
        "$release/venv/bin/python" -m pip --disable-pip-version-check install --no-index --no-deps \
            "$release"/wheelhouse/autodialer-*.whl
        "$release/venv/bin/python" -m pip check
        HF_HUB_OFFLINE=1 runuser -u autodialer-pilot -- "$release/venv/bin/python" - "$release/model" <<'PY'
import sys
from pathlib import Path
from autodialer.verification import DEFAULT_WORKFLOW, OfflineWhisper, SimulatedIVR, classify

whisper = OfflineWhisper(Path(sys.argv[1]))
recording = SimulatedIVR().capture("+12025550101", "12", "confirmed")
label, _ = classify(DEFAULT_WORKFLOW, whisper.transcribe(recording))
if label != "Confirmed":
    raise SystemExit("Offline transcription smoke check did not confirm the fixture.")
PY
        touch "$release/ready"
        rm -rf "$scratch" "$release/wheelhouse"
        scratch=
    fi
    activate "$release"
    for candidate in "$base"/releases/*; do
        if [[ "$candidate" != "$(readlink "$base/current")" &&
              "$candidate" != "$(readlink "$base/previous" || true)" ]]; then
            rm -rf -- "$candidate"
        fi
    done
    printf 'Active release: %s\n' "$version"
}

case "$operation" in
    pair) pair ;;
    deploy) deploy ;;
    rollback)
        previous=$(readlink "$base/previous") || { echo "No previous release is available." >&2; exit 1; }
        activate "$previous"
        printf 'Restored release: %s\n' "$(basename "$previous")"
        ;;
    *) echo "Unknown pilot operation." >&2; exit 1 ;;
esac
