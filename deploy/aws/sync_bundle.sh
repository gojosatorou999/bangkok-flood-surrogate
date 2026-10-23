#!/usr/bin/env bash
# Web machine: mirror s3://$S3_BUCKET/bundle* into /opt/flood/bundle*. The manifest goes last, so the server never sees a
# manifest that points at files that are not there yet. --delete keeps only the newest bundle (yesterday's is removed).
# One bundle per city: bundle/ (Bangkok) and bundle-<city>/ (bundle-hatyai/, ...), each into /opt/flood/<same name>.
set -euo pipefail
names="$(aws s3 ls "s3://${S3_BUCKET}/" | awk '$1 == "PRE" {print $2}' | tr -d / | grep -E '^bundle(-[a-z0-9]+)?$')"   # fails (set -e) if S3 cannot be listed
for name in $names; do
  DEST="/opt/flood/$name"
  mkdir -p "$DEST"
  aws s3 sync "s3://${S3_BUCKET}/$name" "$DEST" --delete --exclude manifest.json --only-show-errors
  aws s3 cp "s3://${S3_BUCKET}/$name/manifest.json" "$DEST/manifest.json" --only-show-errors
done
