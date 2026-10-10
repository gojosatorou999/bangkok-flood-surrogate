#!/usr/bin/env bash
# GPU worker: g4dn.xlarge with an "AWS Deep Learning AMI (PyTorch, Ubuntu)": NVIDIA driver and CUDA torch come with it.
# Run once as root, then STOP the instance; EventBridge Scheduler starts it 4 times a day (see DEPLOY.md).
#   sudo REPO=https://github.com/<you>/bangkok-flood-surrogate.git S3_BUCKET=<bucket> bash setup_worker.sh
set -euo pipefail
: "${REPO:?set REPO}" "${S3_BUCKET:?set S3_BUCKET}"
export DEBIAN_FRONTEND=noninteractive

apt-get update -y && apt-get install -y git python3-venv unzip curl
if ! command -v aws >/dev/null; then
  curl -s "https://awscli.amazonaws.com/awscli-exe-linux-$(uname -m).zip" -o /tmp/awscli.zip
  unzip -q -o /tmp/awscli.zip -d /tmp && /tmp/aws/install
fi

mkdir -p /opt/flood/bundle
if [ -d /opt/flood/app/.git ]; then git -C /opt/flood/app pull; else git clone --depth 1 "$REPO" /opt/flood/app; fi

# a venv that can see the AMI's CUDA torch; the rest comes from pip
python3 -m venv --system-site-packages /opt/flood/venv
if ! /opt/flood/venv/bin/python -c "import torch; assert torch.cuda.is_available()" 2>/dev/null; then
  echo "torch with CUDA not visible in this python: installing it from pytorch.org"
  /opt/flood/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cu126
fi
/opt/flood/venv/bin/pip install -r /opt/flood/app/requirements-worker.txt

printf 'S3_BUCKET=%s\n' "$S3_BUCKET" > /etc/flood.env
chmod +x /opt/flood/app/deploy/aws/*.sh
cp /opt/flood/app/deploy/aws/flood-worker.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable flood-worker.service
echo "installed. Test one run now:  echo FLOOD_KEEP_RUNNING=1 >> /etc/flood.env && sudo /opt/flood/app/deploy/aws/run_worker.sh"
echo "then remove that line from /etc/flood.env and STOP the instance."
