set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Place an expiration timer before package installation so bootstrap failures do not leave compute running.
expires=$(date -u -d '+7 days' '+%Y-%m-%d %H:%M:%S UTC')
cat >/etc/systemd/system/autodialer-expire.timer <<TIMER
[Unit]
Description=Stop the AutoDialer EC2 pilot after seven days

[Timer]
OnCalendar=$expires
Persistent=true
Unit=autodialer-expire.service

[Install]
WantedBy=timers.target
TIMER
cat >/etc/systemd/system/autodialer-expire.service <<'SERVICE'
[Service]
Type=oneshot
ExecStart=/usr/bin/systemctl --no-block poweroff
SERVICE

systemctl daemon-reload
systemctl enable --now autodialer-expire.timer

apt-get -o DPkg::Lock::Timeout=120 update
apt-get -o DPkg::Lock::Timeout=120 install -y awscli ca-certificates curl python3-venv
curl -fsS --retry 3 https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
    -o /usr/share/keyrings/tailscale-archive-keyring.gpg
curl -fsS --retry 3 https://pkgs.tailscale.com/stable/ubuntu/noble.tailscale-keyring.list \
    -o /etc/apt/sources.list.d/tailscale.list
apt-get -o DPkg::Lock::Timeout=120 update
apt-get -o DPkg::Lock::Timeout=120 install -y tailscale
systemctl enable --now tailscaled

useradd --system --user-group --no-create-home --shell /usr/sbin/nologin autodialer-pilot
install -d -m 0755 /opt/autodialer-pilot/releases
install -d -m 0750 -o autodialer-pilot -g autodialer-pilot /var/lib/autodialer-pilot

cat >/etc/systemd/system/autodialer-pilot.service <<'SERVICE'
[Unit]
Description=AutoDialer synthetic pilot
ConditionPathExists=/opt/autodialer-pilot/current/ready
ConditionPathExists=/etc/autodialer-pilot/server.env
After=network.target

[Service]
Type=simple
User=autodialer-pilot
Group=autodialer-pilot
WorkingDirectory=/opt/autodialer-pilot/current
Environment=HF_HUB_OFFLINE=1
EnvironmentFile=/etc/autodialer-pilot/server.env
ExecStart=/opt/autodialer-pilot/current/venv/bin/python -m autodialer.launcher --pilot-host $PILOT_HOST --data-dir /var/lib/autodialer-pilot --model-dir /opt/autodialer-pilot/current/model --no-browser
Restart=on-failure
RestartSec=2
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/lib/autodialer-pilot
IPAddressDeny=any
IPAddressAllow=localhost
UMask=0077

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable autodialer-pilot.service

# Official Ubuntu EC2 images normally include SSM Agent. Install it only if absent.
if ! systemctl is-active --quiet snap.amazon-ssm-agent.amazon-ssm-agent.service &&
   ! systemctl is-active --quiet amazon-ssm-agent.service; then
    if ! snap list amazon-ssm-agent >/dev/null 2>&1; then
        snap install amazon-ssm-agent --classic
    fi
    snap start amazon-ssm-agent
fi
