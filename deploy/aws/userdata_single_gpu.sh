#!/bin/bash
# EC2 user data: turns a fresh GPU instance into the whole backend (NOAA fetch + model + API + HTTPS).
# Use with the "Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu 22.04)" on a g4dn.xlarge.
# Progress log: /var/log/flood-setup.log ; the HTTPS address ends up in /opt/flood/api-url.txt
set -euxo pipefail
exec > >(tee -a /var/log/flood-setup.log) 2>&1

REPO="${REPO:-https://github.com/gojosatorou999/bangkok-flood-surrogate.git}"
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y git python3-venv python3-pip curl gpg debian-keyring debian-archive-keyring apt-transport-https

# Caddy = automatic HTTPS (Let's Encrypt)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
apt-get update -y
apt-get install -y caddy

# app code, model weights and static layers come with the repo (about 40 MB)
id flood >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin flood
mkdir -p /opt/flood
if [ -d /opt/flood/app/.git ]; then git -C /opt/flood/app pull; else git clone --depth 1 "$REPO" /opt/flood/app; fi
chown -R flood:flood /opt/flood

# python environment; CUDA torch only if the image does not already have it
python3 -m venv --system-site-packages /opt/flood/venv
/opt/flood/venv/bin/pip install --upgrade pip
if ! /opt/flood/venv/bin/python -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  /opt/flood/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu126
fi
/opt/flood/venv/bin/pip install -r /opt/flood/app/requirements.txt
chown -R flood:flood /opt/flood

# settings: full mode (NOAA fetch + model on this GPU), read-only public API, any website may call it
TOKEN="$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
cat > /etc/flood.env <<EOF
FLOOD_MODE=full
FLOOD_HOST=127.0.0.1
PORT=8000
FLOOD_READONLY=1
FLOOD_ADMIN_TOKEN=$TOKEN
FLOOD_CORS_ORIGINS=*
EOF
chmod 640 /etc/flood.env && chgrp flood /etc/flood.env

cat > /etc/systemd/system/flood-api.service <<'EOF'
[Unit]
Description=Bangkok flood dashboard API (NOAA GFS + U-Net surrogate)
After=network-online.target
Wants=network-online.target

[Service]
User=flood
WorkingDirectory=/opt/flood/app
EnvironmentFile=/etc/flood.env
ExecStart=/opt/flood/venv/bin/python flood_surrogate.py serve --no-browser
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# the public address is <ip with dashes>.nip.io; it is recomputed every 30 s so it follows an Elastic IP being attached
cat > /usr/local/bin/flood-ipwatch.sh <<'EOF'
#!/bin/bash
set -u
while true; do
  T="$(curl -s -m 3 -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 300' || true)"
  IP="$(curl -s -m 3 -H "X-aws-ec2-metadata-token: $T" http://169.254.169.254/latest/meta-data/public-ipv4 || true)"
  if [ -n "$IP" ] && [ "$IP" != "$(cat /opt/flood/ip 2>/dev/null || true)" ]; then
    HOST="${IP//./-}.nip.io"
    printf '%s {\n\tencode gzip\n\treverse_proxy 127.0.0.1:8000\n}\n' "$HOST" > /etc/caddy/Caddyfile
    echo "$IP" > /opt/flood/ip
    echo "https://$HOST" > /opt/flood/api-url.txt
    systemctl reload caddy 2>/dev/null || systemctl restart caddy
  fi
  sleep 30
done
EOF
chmod +x /usr/local/bin/flood-ipwatch.sh
cat > /etc/systemd/system/flood-ipwatch.service <<'EOF'
[Unit]
Description=Keep the Caddy hostname in step with the instance's public IP
After=network-online.target

[Service]
ExecStart=/usr/local/bin/flood-ipwatch.sh
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# keep the journal small
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/size.conf

systemctl daemon-reload
systemctl restart systemd-journald
systemctl enable --now flood-api.service flood-ipwatch.service
systemctl enable --now caddy
echo "SETUP DONE $(date -u +%FT%TZ)  api-url: $(cat /opt/flood/api-url.txt 2>/dev/null || echo pending)  admin token in /etc/flood.env"
