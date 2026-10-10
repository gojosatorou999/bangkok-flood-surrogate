#!/usr/bin/env bash
# GPU worker: one forecast cycle, publish to S3, then stop the machine (compute billing stops with it).
# Started at boot by flood-worker.service; EventBridge Scheduler starts the instance 4 times a day.
# Set FLOOD_KEEP_RUNNING=1 in /etc/flood.env to keep the instance up for debugging.
set -uo pipefail
source /etc/flood.env
cd /opt/flood/app
export FLOOD_MODE=worker FLOOD_BUNDLE_DIR=/opt/flood/bundle
LOG=/var/log/flood-worker.log

stop_machine() {
  if [ "${FLOOD_KEEP_RUNNING:-0}" != "1" ]; then
    echo "$(date -u +%FT%TZ) stopping in 1 min" >> "$LOG"
    /sbin/shutdown -h +1
  fi
}

# never leave a GPU machine running if something hangs
( sleep 1800; echo "$(date -u +%FT%TZ) watchdog: forcing shutdown" >> "$LOG"; /sbin/shutdown -h now ) &

if /opt/flood/venv/bin/python flood_surrogate.py worker >> "$LOG" 2>&1; then
  if aws s3 sync "$FLOOD_BUNDLE_DIR" "s3://${S3_BUCKET}/bundle" --delete --exclude manifest.json --only-show-errors >> "$LOG" 2>&1 \
     && aws s3 cp "$FLOOD_BUNDLE_DIR/manifest.json" "s3://${S3_BUCKET}/bundle/manifest.json" --only-show-errors >> "$LOG" 2>&1; then
    echo "$(date -u +%FT%TZ) published" >> "$LOG"
  else
    echo "$(date -u +%FT%TZ) upload failed" >> "$LOG"
  fi
else
  echo "$(date -u +%FT%TZ) worker failed" >> "$LOG"
fi
stop_machine
