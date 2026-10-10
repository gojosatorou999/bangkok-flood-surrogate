#!/usr/bin/env bash
# Web machine: mirror s3://$S3_BUCKET/bundle into /opt/flood/bundle. The manifest goes last, so the server never sees a
# manifest that points at files that are not there yet. --delete keeps only the newest bundle (yesterday's is removed).
set -euo pipefail
DEST=/opt/flood/bundle
mkdir -p "$DEST"
aws s3 sync "s3://${S3_BUCKET}/bundle" "$DEST" --delete --exclude manifest.json --only-show-errors
aws s3 cp "s3://${S3_BUCKET}/bundle/manifest.json" "$DEST/manifest.json" --only-show-errors
