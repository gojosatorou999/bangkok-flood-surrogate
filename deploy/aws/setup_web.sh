#!/usr/bin/env bash
# Web machine: Ubuntu 24.04, t3.small (2 GB RAM, no GPU). Run once as root:
#   sudo REPO=https://github.com/<you>/bangkok-flood-surrogate.git S3_BUCKET=<bucket> API_HOST=<ip-with-dashes>.nip.io bash setup_web.sh
set -euo pipefail
: "${REPO:?set REPO}" "${S3_BUCKET:?set S3_BUCKET}" "${API_HOST:?set API_HOST (a name that points at this machine)}"
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y git python3-venv python3-pip unzip curl debian-keyring debian-archive-keyring apt-transport-https gpg

# Caddy: automatic HTTPS
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y && apt-get install -y caddy

# AWS CLI v2
if ! command -v aws >/dev/null; then
  curl -s "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscli.zip
  unzip -q -o /tmp/awscli.zip -d /tmp && /tmp/aws/install
fi

id flood >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin flood
mkdir -p /opt/flood/bundle && chown -R flood:flood /opt/flood
if [ -d /opt/flood/app/.git ]; then
  sudo -u flood git -C /opt/flood/app pull
else
  sudo -u flood git clone --depth 1 "$REPO" /opt/flood/app
fi
sudo -u flood python3 -m venv /opt/flood/venv
sudo -u flood /opt/flood/venv/bin/pip install --upgrade pip
sudo -u flood /opt/flood/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu
sudo -u flood /opt/flood/venv/bin/pip install -r /opt/flood/app/requirements-web.txt

# optional: add FLOOD_ADMIN_TOKEN=<long random string> to enable CCTV uploads (header X-Admin-Token); otherwise every POST is refused
printf 'S3_BUCKET=%s\nAPI_HOST=%s\n' "$S3_BUCKET" "$API_HOST" > /etc/flood.env
chmod 640 /etc/flood.env && chgrp flood /etc/flood.env

cp /opt/flood/app/deploy/aws/flood-web.service /opt/flood/app/deploy/aws/flood-bundle-sync.service /opt/flood/app/deploy/aws/flood-bundle-sync.timer /etc/systemd/system/
cp /opt/flood/app/deploy/aws/Caddyfile /etc/caddy/Caddyfile
mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironmentFile=/etc/flood.env\n' > /etc/systemd/system/caddy.service.d/env.conf
# keep the journal small
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/size.conf
chmod +x /opt/flood/app/deploy/aws/*.sh

# 2 GB swap: the live forecast needs about 1.1 GB RAM, the demo another 0.4 GB while someone uses it
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

systemctl daemon-reload
systemctl restart systemd-journald
systemctl enable --now flood-bundle-sync.timer flood-web.service
systemctl restart caddy
echo "done. Check:  curl https://$API_HOST/api/dash/health"
