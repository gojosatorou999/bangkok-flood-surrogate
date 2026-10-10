"""Unattended DDS road-flood/gauge page snapshotter. See docs/VARUN_IMPLEMENTATION.md §6 T21.

Saves raw bytes only -- no parsing happens in this loop (that's
ingest/dds.py, run offline against the saved snapshots). Same legal-gate
and contact-email discipline as the CCTV archiver (T20): refuses to start
unless every configured endpoint's source is cleared GO.

Run: `tmux new -d -s dds 'make dds-snapshot'`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from cctv.archiver.archiver import user_agent
from cctv.legal_gate import require_go

CONFIG_PATH = Path("configs/cctv.yaml")
ENDPOINTS_PATH = Path("secrets/dds_endpoints.yaml")
RAW_ROOT = Path("data/raw/obs/dds")

EXT_BY_FORMAT = {"json": "json", "html": "html"}

# endpoint kind -> cctv/legal_status.yaml key
KIND_TO_LEGAL_KEY = {"road_flood": "dds_flood", "rain": "dds_scada", "canal": "dds_scada"}


def load_config(config_path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(config_path.read_text())


def load_endpoints(endpoints_path: Path = ENDPOINTS_PATH) -> list[dict]:
    if not endpoints_path.exists():
        return []
    data = yaml.safe_load(endpoints_path.read_text()) or {}
    return data.get("endpoints", [])


def check_legal_gate(endpoints: list[dict], status_path: Path | str | None = None) -> None:
    """Raises LegalGateError (uncaught) unless every endpoint's source is GO."""
    kinds = {e["kind"] for e in endpoints}
    kwargs = {"status_path": status_path} if status_path is not None else {}
    for kind in kinds:
        require_go(KIND_TO_LEGAL_KEY.get(kind, kind), **kwargs)


def _index_path(day_dir: Path) -> Path:
    return day_dir / "_index.jsonl"


def append_index(row: dict, day_dir: Path) -> None:
    day_dir.mkdir(parents=True, exist_ok=True)
    with _index_path(day_dir).open("a") as f:
        f.write(json.dumps(row) + "\n")


async def snapshot_one(
    endpoint: dict,
    client: httpx.AsyncClient,
    cfg: dict,
    *,
    raw_root: Path = RAW_ROOT,
) -> dict:
    """Fetch one endpoint, save the raw bytes, and append an index row.
    Never raises -- a failure becomes a row with status=None/error, so the
    scheduler loop keeps running regardless of one endpoint's failure.
    """
    name, url = endpoint["name"], endpoint["url"]
    ts = datetime.now(timezone.utc)
    ts_utc = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    row: dict = {"name": name, "url": url, "ts_utc": ts_utc}

    day_dir = raw_root / ts.strftime("%Y%m%d")
    ext = EXT_BY_FORMAT.get(endpoint.get("format", "json"), "bin")

    try:
        resp = await client.get(url, timeout=cfg.get("timeout_s", 15))
    except Exception as exc:
        row.update(status=None, error=str(exc)[:200])
        append_index(row, day_dir)
        return row

    content = resp.content
    fname = f"{name}_{ts.strftime('%Y%m%dT%H%MZ')}.{ext}"
    path = day_dir / fname
    day_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)

    row.update(
        status=resp.status_code,
        sha1=hashlib.sha1(content).hexdigest(),
        bytes=len(content),
        path=str(path),
    )
    append_index(row, day_dir)
    return row


def build_scheduler(
    endpoints: list[dict],
    client: httpx.AsyncClient,
    cfg: dict,
) -> AsyncIOScheduler:
    """Builds (but does not start) the scheduler: one interval job per
    endpoint, all sharing the same `dds_snapshot_interval_s`."""
    scheduler = AsyncIOScheduler()
    interval = cfg.get("dds_snapshot_interval_s", 900)
    now = datetime.now(timezone.utc)
    n = max(len(endpoints), 1)
    for i, endpoint in enumerate(endpoints):
        start_offset = (i / n) * interval
        scheduler.add_job(
            snapshot_one,
            trigger=IntervalTrigger(seconds=interval),
            args=[endpoint, client, cfg],
            id=f"dds-{endpoint['name']}",
            max_instances=1,
            coalesce=True,
            next_run_time=now + timedelta(seconds=start_offset),
        )
    return scheduler


async def run() -> None:
    cfg = load_config()
    contact_email = os.environ.get("FG_CONTACT_EMAIL", "")
    if not contact_email:
        raise SystemExit("FG_CONTACT_EMAIL is not set; refusing to start (needed for the User-Agent)")

    endpoints = load_endpoints()
    if not endpoints:
        raise SystemExit("no endpoints in secrets/dds_endpoints.yaml; nothing to snapshot")
    check_legal_gate(endpoints)  # raises LegalGateError, uncaught, if any source isn't GO

    headers = {"User-Agent": user_agent(contact_email)}
    async with httpx.AsyncClient(headers=headers) as client:
        scheduler = build_scheduler(endpoints, client, cfg)
        scheduler.start()
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            scheduler.shutdown(wait=False)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
